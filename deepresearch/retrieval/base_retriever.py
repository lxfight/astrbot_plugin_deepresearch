from abc import ABC, abstractmethod
from typing import List, Dict, Any, Literal, Optional, Set
import asyncio
import time
from datetime import datetime, timedelta

from astrbot.api import star, AstrBotConfig
from ..base_module import BaseModule
from ..data_models import RetrievedItem


class BaseRetriever(BaseModule, ABC):
    """
    所有信息检索器的抽象基类。
    定义了检索信息的通用接口和基础功能。
    """

    # 抽象属性，必须在子类中定义
    source_type: Literal["web", "news", "academic", "custom"]  # 检索器类型，用于识别

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)

        # 确保子类定义了 source_type
        if not hasattr(self, "source_type"):
            raise NotImplementedError(
                f"Retriever class {self.__class__.__name__} must define 'source_type' attribute."
            )

        # 通用配置
        self.search_engines_config = config.get("search_engines", {})
        self.max_results_per_engine = self.search_engines_config.get(
            "max_results_per_engine", 10
        )
        self.search_timeout = self.search_engines_config.get("search_timeout", 30)

        # 网络配置
        self.network_config = config.get("network_config", {})
        self.enable_proxy = self.network_config.get("enable_proxy", False)
        self.proxy_url = self.network_config.get("proxy_url", "")
        self.user_agent = self.network_config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.max_retries = self.network_config.get("max_retries", 3)

        # 性能配置
        self.performance_config = config.get("performance_config", {})
        self.enable_caching = self.performance_config.get("enable_caching", True)
        self.cache_ttl_hours = self.performance_config.get("cache_ttl_hours", 6)

        # 缓存和速率限制
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.rate_limit_records: List[float] = []
        self.rate_limit_per_minute = 60  # 默认每分钟60次请求

        # 统计信息
        self.stats = {
            "total_searches": 0,
            "successful_searches": 0,
            "failed_searches": 0,
            "cache_hits": 0,
            "last_search_time": None,
            "average_response_time": 0.0,
            "total_response_time": 0.0,
        }

        self.logger.debug(
            f"BaseRetriever {self.__class__.__name__} 初始化，类型: {self.source_type}"
        )

    @abstractmethod
    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """
        检查当前检索器是否已正确配置，可以正常工作。
        例如，检查所需的 API Key 是否存在且有效。

        Args:
            api_config: 包含API密钥等配置信息的字典

        Returns:
            如果配置有效则返回 True，否则返回 False
        """
        pass

    @abstractmethod
    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        根据查询词从信息源中检索信息。

        Args:
            query: 搜索查询词
            api_config: 包含API密钥等配置信息的字典

        Returns:
            检索到的信息条目列表
        """
        pass

    async def search_with_fallback(
        self,
        query: str,
        api_config: Dict[str, Any],
        fallback_queries: Optional[List[str]] = None,
    ) -> List[RetrievedItem]:
        """
        带回退机制的搜索，如果主查询失败，尝试备用查询

        Args:
            query: 主要搜索查询
            api_config: API配置
            fallback_queries: 备用查询列表

        Returns:
            检索结果列表
        """
        try:
            # 尝试主查询
            results = await self.search_with_retry(query, api_config)
            if results:
                return results

        except Exception as e:
            self.logger.warning(f"主查询失败: {e}")

        # 如果主查询失败且有备用查询，尝试备用查询
        if fallback_queries:
            for fallback_query in fallback_queries:
                try:
                    self.logger.info(f"尝试备用查询: {fallback_query}")
                    results = await self.search_with_retry(fallback_query, api_config)
                    if results:
                        return results
                except Exception as e:
                    self.logger.warning(f"备用查询失败: {e}")

        return []

    async def search_with_retry(
        self, query: str, api_config: Dict[str, Any], max_retries: Optional[int] = None
    ) -> List[RetrievedItem]:
        """
        带重试机制的搜索

        Args:
            query: 搜索查询
            api_config: API配置
            max_retries: 最大重试次数，None则使用默认配置

        Returns:
            检索结果列表
        """
        max_retries = max_retries or self.max_retries
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                # 检查速率限制
                if not self._check_rate_limit():
                    wait_time = self._calculate_rate_limit_wait()
                    self.logger.info(f"触发速率限制，等待 {wait_time:.1f} 秒")
                    await asyncio.sleep(wait_time)

                # 记录请求
                self._record_request()

                # 执行搜索
                start_time = time.time()
                results = await self._search_with_caching(query, api_config)
                response_time = time.time() - start_time

                # 更新统计
                self._update_stats(True, response_time)

                return results

            except Exception as e:
                last_exception = e
                self._update_stats(False, 0)

                if attempt < max_retries:
                    wait_time = 2**attempt  # 指数退避
                    self.logger.warning(
                        f"搜索失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}，{wait_time}秒后重试"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"搜索最终失败: {e}")

        if last_exception:
            raise last_exception

        return []

    async def _search_with_caching(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        带缓存的搜索
        """
        if self.enable_caching:
            cache_key = self._generate_cache_key(query, api_config)
            cached_result = self._get_cached_result(cache_key)

            if cached_result:
                self.stats["cache_hits"] += 1
                self.logger.debug(f"命中缓存: {query}")
                return cached_result

        # 执行实际搜索
        results = await self.search(query, api_config)

        # 缓存结果
        if self.enable_caching and results:
            self._cache_result(cache_key, results)

        return results

    def _generate_cache_key(self, query: str, api_config: Dict[str, Any]) -> str:
        """生成缓存键"""
        import hashlib

        # 只包含影响搜索结果的配置项
        relevant_config = {
            k: v
            for k, v in api_config.items()
            if v and k in self.get_required_config_keys()
        }

        cache_data = (
            f"{self.source_type}:{query}:{str(sorted(relevant_config.items()))}"
        )
        return hashlib.md5(cache_data.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[List[RetrievedItem]]:
        """获取缓存结果"""
        if cache_key not in self.cache:
            return None

        cached_data = self.cache[cache_key]
        cache_time = cached_data["timestamp"]
        cache_ttl = timedelta(hours=self.cache_ttl_hours)

        if datetime.now() - cache_time > cache_ttl:
            del self.cache[cache_key]
            return None

        return cached_data["results"]

    def _cache_result(self, cache_key: str, results: List[RetrievedItem]):
        """缓存搜索结果"""
        self.cache[cache_key] = {"results": results, "timestamp": datetime.now()}

    def _check_rate_limit(self) -> bool:
        """检查是否超过速率限制"""
        current_time = time.time()
        # 清理过期的记录
        self.rate_limit_records = [
            t
            for t in self.rate_limit_records
            if current_time - t < 60  # 保留最近1分钟的记录
        ]

        return len(self.rate_limit_records) < self.rate_limit_per_minute

    def _calculate_rate_limit_wait(self) -> float:
        """计算需要等待的时间"""
        if not self.rate_limit_records:
            return 0

        oldest_record = min(self.rate_limit_records)
        return 60 - (time.time() - oldest_record)

    def _record_request(self):
        """记录请求时间"""
        self.rate_limit_records.append(time.time())

    def _update_stats(self, success: bool, response_time: float):
        """更新统计信息"""
        self.stats["total_searches"] += 1
        self.stats["last_search_time"] = datetime.now().isoformat()

        if success:
            self.stats["successful_searches"] += 1
            self.stats["total_response_time"] += response_time
            self.stats["average_response_time"] = (
                self.stats["total_response_time"] / self.stats["successful_searches"]
            )
        else:
            self.stats["failed_searches"] += 1

    def get_required_config_keys(self) -> Set[str]:
        """
        获取此检索器所需的配置键集合
        子类可以重写此方法来指定具体的配置需求
        """
        return set()

    def validate_config_completeness(
        self, api_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证配置完整性

        Returns:
            包含验证结果的字典
        """
        required_keys = self.get_required_config_keys()
        missing_keys = []
        invalid_keys = []

        for key in required_keys:
            if key not in api_config:
                missing_keys.append(key)
            elif not api_config[key]:
                invalid_keys.append(key)

        is_valid = len(missing_keys) == 0 and len(invalid_keys) == 0

        return {
            "valid": is_valid,
            "missing_keys": missing_keys,
            "invalid_keys": invalid_keys,
            "required_keys": list(required_keys),
            "basic_check": self.check_config_valid(api_config),
        }

    def filter_results(
        self, results: List[RetrievedItem], min_quality_score: float = 0.0
    ) -> List[RetrievedItem]:
        """
        过滤搜索结果

        Args:
            results: 原始搜索结果
            min_quality_score: 最小质量评分

        Returns:
            过滤后的结果
        """
        filtered_results = []

        for result in results:
            # 基本有效性检查
            if not result.url or not result.title:
                continue

            # 计算质量评分（如果没有relevance_score或需要重新计算）
            if result.relevance_score == 0.0:
                result.relevance_score = self._calculate_quality_score(result)

            quality_score = result.relevance_score
            if quality_score < min_quality_score:
                continue

            # 确保元数据存在
            if not result.metadata:
                result.metadata = {}
            result.metadata["quality_score"] = quality_score
            result.metadata["filtered_at"] = datetime.now().isoformat()

            filtered_results.append(result)

        # 按相关性评分排序
        filtered_results.sort(key=lambda x: x.relevance_score, reverse=True)

        return filtered_results

    def _calculate_quality_score(self, result: RetrievedItem) -> float:
        """
        计算结果质量评分
        子类可以重写此方法来实现特定的质量评估逻辑
        """
        score = 0.0

        # 标题质量
        if result.title:
            if len(result.title) > 10:
                score += 0.3
            if not any(
                spam in result.title.lower() for spam in ["点击", "免费", "广告"]
            ):
                score += 0.2

        # 描述质量
        if result.snippet:
            if len(result.snippet) > 20:
                score += 0.3
            if len(result.snippet.split()) > 5:
                score += 0.2

        # 如果有已存在的相关性评分，考虑进去
        if hasattr(result, "relevance_score") and result.relevance_score > 0:
            score = (score * 0.7) + (result.relevance_score * 0.3)

        return min(score, 1.0)

    def get_statistics(self) -> Dict[str, Any]:
        """获取检索器统计信息"""
        return {
            "source_type": self.source_type,
            "stats": self.stats.copy(),
            "cache_size": len(self.cache),
            "rate_limit_remaining": self.rate_limit_per_minute
            - len(self.rate_limit_records),
            "config_valid": True,  # 基础检查，具体实现可能需要实际验证
        }

    def clear_cache(self):
        """清理缓存"""
        self.cache.clear()
        self.logger.debug(f"{self.__class__.__name__} 缓存已清理")

    def reset_statistics(self):
        """重置统计信息"""
        self.stats = {
            "total_searches": 0,
            "successful_searches": 0,
            "failed_searches": 0,
            "cache_hits": 0,
            "last_search_time": None,
            "average_response_time": 0.0,
            "total_response_time": 0.0,
        }
        self.logger.debug(f"{self.__class__.__name__} 统计信息已重置")

    def get_health_status(self) -> Dict[str, Any]:
        """获取健康状态"""
        total_searches = self.stats["total_searches"]
        success_rate = 0.0

        if total_searches > 0:
            success_rate = self.stats["successful_searches"] / total_searches

        # 确定健康状态
        if success_rate >= 0.9:
            status = "healthy"
        elif success_rate >= 0.7:
            status = "warning"
        else:
            status = "unhealthy"

        return {
            "status": status,
            "success_rate": success_rate,
            "total_searches": total_searches,
            "last_search": self.stats["last_search_time"],
            "average_response_time": self.stats["average_response_time"],
            "cache_hit_rate": self.stats["cache_hits"] / max(total_searches, 1),
        }

    async def test_connection(self, api_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        测试连接（执行简单的测试搜索）

        Returns:
            测试结果字典
        """
        test_query = "test"
        start_time = time.time()

        try:
            results = await self.search(test_query, api_config)
            response_time = time.time() - start_time

            return {
                "success": True,
                "response_time": response_time,
                "results_count": len(results),
                "message": "连接测试成功",
            }

        except Exception as e:
            response_time = time.time() - start_time

            return {
                "success": False,
                "response_time": response_time,
                "error": str(e),
                "message": "连接测试失败",
            }

    def cleanup(self):
        """清理资源"""
        self.clear_cache()
        self.reset_statistics()
        self.rate_limit_records.clear()
        self.logger.debug(f"{self.__class__.__name__} 资源已清理")

    # 高级功能统一接口，子类可选择实现
    async def search_by_site(self, query: str, site: str, api_config: Dict[str, Any]) -> List[RetrievedItem]:
        """
        站点内搜索（如支持）
        """
        raise NotImplementedError("该检索器未实现站点内搜索接口")

    async def search_exact_phrase(self, phrase: str, api_config: Dict[str, Any]) -> List[RetrievedItem]:
        """
        精确短语搜索（如支持）
        """
        raise NotImplementedError("该检索器未实现精确短语搜索接口")

    async def search_with_date_filter(self, query: str, api_config: Dict[str, Any], date_restrict: str = "m1") -> List[RetrievedItem]:
        """
        带日期过滤的搜索（如支持）
        """
        raise NotImplementedError("该检索器未实现日期过滤接口")
