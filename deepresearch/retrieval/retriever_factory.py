from typing import Dict, Optional, Literal, Any, Set
import asyncio
from datetime import datetime

from astrbot.api import star, AstrBotConfig
from ..base_module import BaseModule
from .base_retriever import BaseRetriever
from .retriever_registry import RetrieverRegistry


class RetrieverFactory(BaseModule):
    """
    检索器工厂，根据配置动态创建和提供可用的检索器实例。
    支持配置验证、健康检查、动态重载等功能。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self._available_retrievers: Dict[str, BaseRetriever] = {}
        self._failed_retrievers: Dict[str, str] = {}  # 记录失败的检索器及原因
        self._retriever_health: Dict[str, Dict[str, Any]] = {}  # 检索器健康状态
        self._enabled_engines: Set[str] = set()  # 启用的搜索引擎

        # 从配置中获取启用的搜索引擎
        search_engines_config = self.config.get("search_engines", {})
        enabled_engines_list = search_engines_config.get(
            "enabled_engines", ["duckduckgo", "bing", "google"]
        )
        self._enabled_engines = set(enabled_engines_list)

        # 初始化检索器
        self.initialize_retrievers()

        # 启动健康检查任务（如果配置启用）
        debug_config = self.config.get("debug_config", {})
        if debug_config.get("enable_verbose_logging", False):
            asyncio.create_task(self._periodic_health_check())

        self.logger.info(
            f"RetrieverFactory 模块初始化完成，已载入 {len(self._available_retrievers)} 个检索器"
        )

    def initialize_retrievers(self):
        """
        初始化所有已注册且配置有效的检索器。
        """
        self.logger.info("开始初始化检索器...")

        # 清空之前的状态
        self._available_retrievers.clear()
        self._failed_retrievers.clear()
        self._retriever_health.clear()

        # 获取配置
        search_config = self._extract_search_config()

        # 检查 news_search、academic_search 的 enabled 字段
        news_enabled = self.config.get("news_search", {}).get("enabled", True)
        academic_enabled = self.config.get("academic_search", {}).get("enabled", False)

        # 按优先级顺序初始化检索器
        initialization_order = RetrieverRegistry.get_initialization_order()
        registry_classes = RetrieverRegistry.get_retriever_classes()

        for source_type in initialization_order:
            if source_type not in registry_classes:
                continue

            # 检查是否在启用列表中
            if not self._is_engine_enabled(source_type):
                self.logger.info(f"检索器 '{source_type}' 未在启用列表中，跳过初始化")
                continue

            # 检查 enabled 字段
            if source_type == "news" and not news_enabled:
                self.logger.info("news_search 未启用，跳过初始化")
                continue
            if source_type == "academic" and not academic_enabled:
                self.logger.info("academic_search 未启用，跳过初始化")
                continue

            retriever_cls = registry_classes[source_type]

            try:
                self._initialize_single_retriever(
                    source_type, retriever_cls, search_config
                )
            except Exception as e:
                error_msg = (
                    f"初始化检索器 '{retriever_cls.__name__}' ({source_type}) 失败: {e}"
                )
                self.logger.error(error_msg, exc_info=True)
                self._failed_retrievers[source_type] = str(e)

        # 记录初始化结果
        self._log_initialization_summary()

    def _extract_search_config(self) -> Dict[str, Any]:
        """提取所有搜索引擎相关的配置"""
        config_mapping = {
            "google_cse_api_key": ("google_search", "cse_api_key"),
            "google_cse_cx": ("google_search", "cse_cx"),
            "bing_api_key": ("bing_search", "api_key"),
            "bing_endpoint": ("bing_search", "endpoint"),
            "serper_api_key": ("serper_search", "api_key"),
            "baidu_api_key": ("baidu_search", "api_key"),
            "baidu_secret_key": ("baidu_search", "secret_key"),
            "news_api_key": ("news_search", "news_api_key"),
            "academic_search_api_key": ("academic_search", "semantic_scholar_api_key"),
        }

        # 提取配置
        search_config = {}

        # 从新配置结构中提取
        for config_key, (section, key) in config_mapping.items():
            section_config = self.config.get(section, {})
            value = section_config.get(key, "")
            if value:
                search_config[config_key] = value

        # 保持向后兼容性，从旧的search_config中提取
        old_search_config = self.config.get("search_config", {})
        search_config.update(old_search_config)

        return search_config

    def _is_engine_enabled(self, source_type: str) -> bool:
        """检查搜索引擎是否启用"""
        # 特殊处理映射
        engine_mapping = {
            "web": ["google", "bing", "serper", "duckduckgo"],
            "news": ["news"],
            "academic": ["academic"],
        }

        if source_type in self._enabled_engines:
            return True

        # 检查映射的引擎类型
        mapped_engines = engine_mapping.get(source_type, [])
        return any(engine in self._enabled_engines for engine in mapped_engines)

    def _initialize_single_retriever(
        self, source_type: str, retriever_cls: type, search_config: Dict[str, Any]
    ):
        """初始化单个检索器"""
        start_time = datetime.now()

        try:
            # 实例化检索器
            retriever_instance = retriever_cls(self.context, self.config)

            # 检查配置是否有效
            config_valid = retriever_instance.check_config_valid(search_config)

            if config_valid:
                self._available_retrievers[source_type] = retriever_instance

                # 记录健康状态
                self._retriever_health[source_type] = {
                    "status": "healthy",
                    "initialized_at": start_time.isoformat(),
                    "last_check": start_time.isoformat(),
                    "config_valid": True,
                    "error_count": 0,
                    "last_error": None,
                }

                self.logger.info(
                    f"检索器 '{retriever_cls.__name__}' ({source_type}) 配置有效并已载入"
                )
            else:
                error_msg = "检索器配置无效"
                self._failed_retrievers[source_type] = error_msg

                self._retriever_health[source_type] = {
                    "status": "config_invalid",
                    "initialized_at": start_time.isoformat(),
                    "last_check": start_time.isoformat(),
                    "config_valid": False,
                    "error_count": 1,
                    "last_error": error_msg,
                }

                self.logger.warning(
                    f"检索器 '{retriever_cls.__name__}' ({source_type}) 配置无效，将跳过载入"
                )

        except Exception as e:
            error_msg = str(e)
            self._failed_retrievers[source_type] = error_msg

            self._retriever_health[source_type] = {
                "status": "failed",
                "initialized_at": start_time.isoformat(),
                "last_check": start_time.isoformat(),
                "config_valid": False,
                "error_count": 1,
                "last_error": error_msg,
            }

            raise

    def _log_initialization_summary(self):
        """记录初始化摘要"""
        total_available = len(RetrieverRegistry.get_retriever_classes())
        loaded_count = len(self._available_retrievers)
        # failed_count = len(self._failed_retrievers)

        self.logger.info(f"检索器初始化完成: {loaded_count}/{total_available} 成功载入")

        if self._available_retrievers:
            self.logger.info(f"可用检索器: {list(self._available_retrievers.keys())}")

        if self._failed_retrievers:
            self.logger.warning(f"失败检索器: {list(self._failed_retrievers.keys())}")
            for source_type, error in self._failed_retrievers.items():
                self.logger.debug(f"  {source_type}: {error}")

    async def _periodic_health_check(self):
        """定期健康检查"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟检查一次
                await self.health_check_all()
            except Exception as e:
                self.logger.error(f"定期健康检查失败: {e}")

    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """对所有检索器进行健康检查"""
        health_results = {}

        for source_type, retriever in self._available_retrievers.items():
            try:
                # 执行简单的健康检查（可以是配置验证或简单的API调用）
                search_config = self._extract_search_config()
                is_healthy = retriever.check_config_valid(search_config)

                current_time = datetime.now()
                if is_healthy:
                    self._retriever_health[source_type]["status"] = "healthy"
                    self._retriever_health[source_type]["last_check"] = (
                        current_time.isoformat()
                    )
                else:
                    self._retriever_health[source_type]["status"] = "unhealthy"
                    self._retriever_health[source_type]["error_count"] += 1
                    self._retriever_health[source_type]["last_error"] = "配置验证失败"

                health_results[source_type] = self._retriever_health[source_type].copy()

            except Exception as e:
                self._retriever_health[source_type]["status"] = "error"
                self._retriever_health[source_type]["error_count"] += 1
                self._retriever_health[source_type]["last_error"] = str(e)
                health_results[source_type] = self._retriever_health[source_type].copy()

        return health_results

    def get_available_retrievers(self) -> Dict[str, BaseRetriever]:
        """
        获取当前已实例化且配置有效的检索器字典。
        按 priority 降序排序。
        """
        # 按 priority 排序
        retrievers = list(self._available_retrievers.items())
        retrievers.sort(
            key=lambda kv: getattr(kv[1].__class__, "_registry_priority", 0),
            reverse=True,
        )
        return dict(retrievers)

    # 动态注册检索器
    def register_retriever_dynamic(
        self,
        retriever_cls: type,
        source_type: str,
        alias: str = None,
        priority: int = 0,
    ) -> bool:
        """
        动态注册新的检索器类
        """
        try:
            RetrieverRegistry.register(source_type, alias, priority)(retriever_cls)
            self.logger.info(
                f"动态注册检索器 {retriever_cls.__name__} ({source_type}) 成功"
            )
            self.reload_retriever(source_type)
            return True
        except Exception as e:
            self.logger.error(f"动态注册检索器失败: {e}")
            return False

    # 动态注销检索器
    def unregister_retriever_dynamic(self, source_type: str) -> bool:
        """
        动态注销检索器
        """
        try:
            RetrieverRegistry.unregister(source_type)
            if source_type in self._available_retrievers:
                del self._available_retrievers[source_type]
            if source_type in self._failed_retrievers:
                del self._failed_retrievers[source_type]
            if source_type in self._retriever_health:
                del self._retriever_health[source_type]
            self.logger.info(f"动态注销检索器 {source_type} 成功")
            return True
        except Exception as e:
            self.logger.error(f"动态注销检索器失败: {e}")
            return False

    def get_retriever_health(self, source_type: Optional[str] = None) -> Dict[str, Any]:
        """获取检索器健康状态（对外接口）"""
        if source_type:
            return self._retriever_health.get(source_type, {})
        return self._retriever_health.copy()

    async def call_advanced_search(
        self, source_type: str, method: str, *args, **kwargs
    ):
        """
        统一调用高级接口（如 search_by_site、search_exact_phrase、search_with_date_filter）
        """
        retriever = self._available_retrievers.get(source_type)
        if not retriever:
            raise Exception(f"检索器 {source_type} 不可用")
        if not hasattr(retriever, method):
            raise Exception(f"检索器 {source_type} 不支持方法 {method}")
        func = getattr(retriever, method)
        return await func(*args, **kwargs)

    def get_failed_retrievers(self) -> Dict[str, str]:
        """获取初始化失败的检索器及失败原因"""
        return self._failed_retrievers.copy()

    def get_retriever_health(self, source_type: Optional[str] = None) -> Dict[str, Any]:
        """获取检索器健康状态"""
        if source_type:
            return self._retriever_health.get(source_type, {})
        return self._retriever_health.copy()

    def reload_retriever(self, source_type: str) -> bool:
        """重新加载指定的检索器"""
        try:
            registry_classes = RetrieverRegistry.get_retriever_classes()
            if source_type not in registry_classes:
                self.logger.error(f"未找到类型为 '{source_type}' 的检索器类")
                return False

            # 移除旧实例
            if source_type in self._available_retrievers:
                del self._available_retrievers[source_type]
            if source_type in self._failed_retrievers:
                del self._failed_retrievers[source_type]

            # 重新初始化
            retriever_cls = registry_classes[source_type]
            search_config = self._extract_search_config()
            self._initialize_single_retriever(source_type, retriever_cls, search_config)

            self.logger.info(f"检索器 '{source_type}' 重新加载成功")
            return True

        except Exception as e:
            self.logger.error(
                f"重新加载检索器 '{source_type}' 失败: {e}", exc_info=True
            )
            return False

    def reload_all_retrievers(self) -> Dict[str, bool]:
        """重新加载所有检索器"""
        results = {}
        for source_type in list(self._available_retrievers.keys()) + list(
            self._failed_retrievers.keys()
        ):
            results[source_type] = self.reload_retriever(source_type)
        return results

    def get_factory_statistics(self) -> Dict[str, Any]:
        """获取工厂统计信息"""
        total_registered = len(RetrieverRegistry.get_retriever_classes())
        total_enabled = len(
            [
                t
                for t in RetrieverRegistry.list_available_types()
                if self._is_engine_enabled(t)
            ]
        )

        return {
            "total_registered": total_registered,
            "total_enabled": total_enabled,
            "total_loaded": len(self._available_retrievers),
            "total_failed": len(self._failed_retrievers),
            "enabled_engines": list(self._enabled_engines),
            "available_retrievers": list(self._available_retrievers.keys()),
            "failed_retrievers": list(self._failed_retrievers.keys()),
            "health_summary": {
                "healthy": len(
                    [
                        h
                        for h in self._retriever_health.values()
                        if h.get("status") == "healthy"
                    ]
                ),
                "unhealthy": len(
                    [
                        h
                        for h in self._retriever_health.values()
                        if h.get("status") != "healthy"
                    ]
                ),
            },
        }

    def validate_config(self, config_section: str) -> Dict[str, Any]:
        """验证特定配置段的有效性"""
        validation_results = {}

        # 提取指定配置段
        section_config = self.config.get(config_section, {})

        # 验证每个已注册的检索器对该配置的要求
        for source_type, metadata in RetrieverRegistry._retrievers.items():
            try:
                # 创建临时实例进行验证
                temp_instance = metadata.retriever_cls(self.context, self.config)
                is_valid = temp_instance.check_config_valid(section_config)

                validation_results[source_type] = {
                    "valid": is_valid,
                    "requirements": metadata.config_requirements,
                    "provided_keys": list(section_config.keys()),
                }

            except Exception as e:
                validation_results[source_type] = {"valid": False, "error": str(e)}

        return validation_results

    def get_configuration_recommendations(self) -> Dict[str, Any]:
        """获取配置建议"""
        recommendations = {
            "missing_configs": {},
            "optional_configs": {},
            "enabled_but_unconfigured": [],
        }

        search_config = self._extract_search_config()

        for source_type, metadata in RetrieverRegistry._retrievers.items():
            if not self._is_engine_enabled(source_type):
                continue

            # 检查必需配置
            missing_configs = []
            for req in metadata.config_requirements:
                if req not in search_config or not search_config[req]:
                    missing_configs.append(req)

            if missing_configs:
                recommendations["missing_configs"][source_type] = missing_configs

            # 检查启用但未配置的引擎
            if source_type in self._failed_retrievers:
                recommendations["enabled_but_unconfigured"].append(source_type)

        return recommendations

    def cleanup(self):
        """清理资源"""
        try:
            self._available_retrievers.clear()
            self._failed_retrievers.clear()
            self._retriever_health.clear()
            self.logger.info("RetrieverFactory 资源已清理")
        except Exception as e:
            self.logger.error(f"RetrieverFactory 清理失败: {e}")
