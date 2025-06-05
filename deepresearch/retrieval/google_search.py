import aiohttp
from typing import List, Dict, Any, Set, Optional
import json
from datetime import datetime

from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("web", alias="google", priority=10)
class GoogleSearchRetriever(BaseRetriever):
    """
    Google Custom Search API 检索器实现
    使用 Google Custom Search Engine 进行网页搜索
    """

    def __init__(self, context, config):
        super().__init__(context, config)

        # Google搜索特定配置
        self.google_config = config.get("google_search", {})
        self.cse_api_key = self.google_config.get("cse_api_key", "")
        self.cse_cx = self.google_config.get("cse_cx", "")
        self.search_url = "https://www.googleapis.com/customsearch/v1"

        # 搜索参数配置
        self.default_params = {
            "num": min(self.max_results_per_engine, 10),  # Google CSE 最多返回10个结果
            "safe": "medium",  # 安全搜索级别
            "lr": "lang_zh|lang_en",  # 语言限制
            "gl": "cn",  # 地理位置
            "dateRestrict": "y1",  # 限制为最近一年的结果
        }

        # 速率限制 (Google CSE 免费版本每日100次查询)
        self.rate_limit_per_minute = 100  # 保守设置

        self.logger.info("GoogleSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        """获取Google搜索所需的配置键"""
        return {"google_cse_api_key", "google_cse_cx"}

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """检查Google Custom Search配置是否有效"""
        # 检查必需的API配置
        cse_api_key = api_config.get("google_cse_api_key", self.cse_api_key)
        cse_cx = api_config.get("google_cse_cx", self.cse_cx)

        if not cse_api_key or not cse_cx:
            self.logger.warning(
                "Google Custom Search API Key 或 Search Engine ID 未配置"
            )
            return False

        # 验证API Key格式（Google API Key通常以AIza开头）
        if not cse_api_key.startswith("AIza") or len(cse_api_key) < 35:
            self.logger.warning("Google API Key 格式可能不正确")
            return False

        # 验证Search Engine ID格式
        if len(cse_cx) < 10:
            self.logger.warning("Google Custom Search Engine ID 格式可能不正确")
            return False

        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """执行Google搜索"""
        if not query.strip():
            return []

        # 获取API配置
        cse_api_key = api_config.get("google_cse_api_key", self.cse_api_key)
        cse_cx = api_config.get("google_cse_cx", self.cse_cx)

        if not self.check_config_valid(api_config):
            self.logger.error("Google搜索配置无效，无法执行搜索")
            return []

        try:
            # 构建搜索参数
            params = self.default_params.copy()
            params.update({"key": cse_api_key, "cx": cse_cx, "q": query})

            # 执行搜索请求
            results = await self._execute_search_request(params)

            # 处理和过滤结果
            retrieved_items = self._parse_search_results(results, query)

            # 应用质量过滤
            filtered_items = self.filter_results(retrieved_items, min_quality_score=0.3)

            self.logger.info(
                f"Google搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
            )
            return filtered_items

        except Exception as e:
            self.logger.error(f"Google搜索出错: {e}", exc_info=True)
            return []

    async def _execute_search_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行搜索请求"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # 配置代理
        connector_kwargs = {}
        if self.enable_proxy and self.proxy_url:
            connector_kwargs["connector"] = aiohttp.TCPConnector(
                limit=100, ttl_dns_cache=300
            )

        timeout = aiohttp.ClientTimeout(total=self.search_timeout)

        async with aiohttp.ClientSession(
            headers=headers, timeout=timeout, **connector_kwargs
        ) as session:
            # 如果启用代理，在请求中使用
            request_kwargs = {}
            if self.enable_proxy and self.proxy_url:
                request_kwargs["proxy"] = self.proxy_url

            async with session.get(
                self.search_url, params=params, **request_kwargs
            ) as response:
                if response.status == 429:
                    raise Exception("Google搜索API配额已用完或请求过于频繁")
                elif response.status == 403:
                    raise Exception("Google搜索API访问被拒绝，请检查API Key和权限")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Google搜索API返回错误 {response.status}: {error_text}"
                    )

                try:
                    data = await response.json()
                    return data
                except json.JSONDecodeError as e:
                    raise Exception(f"Google搜索API返回无效JSON: {e}")

    def _parse_search_results(
        self, data: Dict[str, Any], query: str
    ) -> List[RetrievedItem]:
        """解析Google搜索结果"""
        results = []

        try:
            # 检查是否有搜索结果
            if "items" not in data:
                if "error" in data:
                    error_info = data["error"]
                    self.logger.error(
                        f"Google搜索API错误: {error_info.get('message', 'Unknown error')}"
                    )
                else:
                    self.logger.info("Google搜索未返回结果")
                return results

            # 解析每个搜索结果
            for i, item in enumerate(data["items"]):
                try:
                    # 提取基本信息
                    title = item.get("title", "").strip()
                    url = item.get("link", "").strip()
                    snippet = item.get("snippet", "").strip()

                    if not url or not title:
                        continue

                    # 提取发布日期
                    published_date = self._extract_published_date(item)

                    # 创建检索项，确保符合RetrievedItem模型
                    retrieved_item = RetrievedItem(
                        url=url,
                        title=title,
                        snippet=snippet,
                        source_type="web",
                        source="google",  # 明确指定来源为google
                        published_date=published_date,
                        relevance_score=self._calculate_initial_relevance_score(
                            item, query, i
                        ),
                        raw_source_data=item,  # 保存原始数据用于调试
                    )

                    # 添加元数据
                    retrieved_item.metadata = self._extract_metadata(item, i)

                    results.append(retrieved_item)

                except Exception as e:
                    self.logger.warning(f"解析Google搜索结果项时出错: {e}")
                    continue

            self.logger.debug(f"Google搜索解析了 {len(results)} 个结果")

        except Exception as e:
            self.logger.error(f"解析Google搜索结果时出错: {e}", exc_info=True)

        return results

    def _extract_published_date(self, item: Dict[str, Any]) -> Optional[datetime]:
        """提取发布日期"""
        try:
            # 尝试从pagemap中提取发布时间
            if "pagemap" in item and "metatags" in item["pagemap"]:
                metatags = item["pagemap"]["metatags"]
                if metatags:
                    meta = metatags[0]

                    # 尝试多种日期字段
                    date_fields = [
                        "article:published_time",
                        "published_time",
                        "date",
                        "pubdate",
                        "dc.date",
                    ]

                    for field in date_fields:
                        if field in meta and meta[field]:
                            try:
                                from dateutil import parser

                                return parser.parse(meta[field])
                            except Exception as e:
                                self.logger.debug(f"解析发布日期失败: {e}")
                                continue

            # 如果无法提取具体日期，返回None
            return None

        except Exception as e:
            self.logger.debug(f"提取发布日期失败: {e}")
            return None

    def _calculate_initial_relevance_score(
        self, item: Dict[str, Any], query: str, rank: int
    ) -> float:
        """计算初始相关性评分"""
        try:
            score = 0.0

            # 基于排名的评分（排名越靠前分数越高）
            rank_score = max(0, (10 - rank) / 10.0)
            score += rank_score * 0.4

            # 基于标题匹配度的评分
            title = item.get("title", "").lower()
            query_terms = set(query.lower().split())
            title_terms = set(title.split())

            if query_terms and title_terms:
                title_match = len(query_terms & title_terms) / len(query_terms)
                score += title_match * 0.3

            # 基于摘要匹配度的评分
            snippet = item.get("snippet", "").lower()
            if snippet and query_terms:
                snippet_terms = set(snippet.split())
                snippet_match = len(query_terms & snippet_terms) / len(query_terms)
                score += snippet_match * 0.2

            # 基于URL质量的评分
            url = item.get("link", "")
            if url:
                domain_score = self._evaluate_domain_credibility(url)
                score += domain_score * 0.1

            return min(score, 1.0)

        except Exception as e:
            self.logger.debug(f"计算初始相关性评分失败: {e}")
            return 0.5  # 默认评分

    def _extract_metadata(self, item: Dict[str, Any], rank: int) -> Dict[str, Any]:
        """提取搜索结果的元数据"""
        metadata = {
            "rank": rank + 1,
            "search_engine": "google",
            "display_url": item.get("displayLink", ""),
            "cached_url": item.get("cacheId", ""),
            "formatted_url": item.get("formattedUrl", ""),
        }

        # 提取页面信息
        if "pagemap" in item:
            pagemap = item["pagemap"]

            # 提取网站图标
            if "cse_thumbnail" in pagemap:
                thumbnails = pagemap["cse_thumbnail"]
                if thumbnails:
                    metadata["thumbnail"] = thumbnails[0].get("src", "")

            # 提取网站信息
            if "website" in pagemap:
                websites = pagemap["website"]
                if websites:
                    website_info = websites[0]
                    metadata["site_name"] = website_info.get("name", "")
                    metadata["site_description"] = website_info.get("description", "")

            # 提取元标签信息
            if "metatags" in pagemap:
                metatags = pagemap["metatags"]
                if metatags:
                    meta = metatags[0]
                    metadata["og_title"] = meta.get("og:title", "")
                    metadata["og_description"] = meta.get("og:description", "")
                    metadata["og_image"] = meta.get("og:image", "")
                    metadata["author"] = meta.get("author", "")
                    metadata["published_time"] = meta.get("article:published_time", "")

        return metadata

    def _calculate_quality_score(self, result: RetrievedItem) -> float:
        """计算Google搜索结果的质量评分"""
        score = super()._calculate_quality_score(result)

        # Google特定的质量评分增强
        if result.metadata:
            # 有缩略图加分
            if result.metadata.get("thumbnail"):
                score += 0.1

            # 有Open Graph信息加分
            if result.metadata.get("og_title") or result.metadata.get("og_description"):
                score += 0.1

            # 有作者信息加分
            if result.metadata.get("author"):
                score += 0.05

            # 有发布时间加分
            if result.metadata.get("published_time"):
                score += 0.05

            # 排名靠前加分
            rank = result.metadata.get("rank", 11)
            if rank <= 3:
                score += 0.2
            elif rank <= 5:
                score += 0.1
            elif rank <= 7:
                score += 0.05

        # 域名可信度评分
        if result.url:
            domain_score = self._evaluate_domain_credibility(result.url)
            score += domain_score * 0.1

        return min(score, 1.0)

    def _evaluate_domain_credibility(self, url: str) -> float:
        """评估域名可信度"""
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.lower()

            # 高可信度域名
            trusted_domains = {
                # 政府机构
                "gov.cn",
                "gov.com",
                "government.cn",
                # 教育机构
                "edu.cn",
                "edu.com",
                "university.edu",
                # 知名媒体
                "xinhuanet.com",
                "people.com.cn",
                "cctv.com",
                "chinadaily.com.cn",
                # 国际知名网站
                "wikipedia.org",
                "bbc.com",
                "reuters.com",
                "nature.com",
                "science.org",
                # 技术网站
                "github.com",
                "stackoverflow.com",
                "medium.com",
            }

            # 检查是否为可信域名
            for trusted in trusted_domains:
                if trusted in domain:
                    return 1.0

            # 检查域名特征
            if any(indicator in domain for indicator in [".gov.", ".edu.", ".org."]):
                return 0.8
            elif any(indicator in domain for indicator in [".com.", ".net.", ".cn"]):
                return 0.6
            else:
                return 0.4

        except Exception:
            return 0.5

    async def search_with_date_filter(
        self, query: str, api_config: Dict[str, Any], date_restrict: str = "m1"
    ) -> List[RetrievedItem]:
        """
        带日期过滤的搜索

        Args:
            query: 搜索查询
            api_config: API配置
            date_restrict: 日期限制 (d1=1天, w1=1周, m1=1月, y1=1年)
        """
        # 临时修改默认参数
        original_date_restrict = self.default_params.get("dateRestrict")
        self.default_params["dateRestrict"] = date_restrict

        try:
            results = await self.search(query, api_config)
            return results
        finally:
            # 恢复原始参数
            if original_date_restrict:
                self.default_params["dateRestrict"] = original_date_restrict
            else:
                self.default_params.pop("dateRestrict", None)

    async def search_by_site(
        self, query: str, site: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        站点内搜索

        Args:
            query: 搜索查询
            site: 指定站点域名
            api_config: API配置
        """
        site_query = f"site:{site} {query}"
        return await self.search(site_query, api_config)

    async def search_exact_phrase(
        self, phrase: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        精确短语搜索

        Args:
            phrase: 要精确匹配的短语
            api_config: API配置
        """
        exact_query = f'"{phrase}"'
        return await self.search(exact_query, api_config)

    def get_search_statistics(self) -> Dict[str, Any]:
        """获取Google搜索的统计信息"""
        base_stats = self.get_statistics()

        google_specific_stats = {
            "search_engine": "Google Custom Search",
            "api_endpoint": self.search_url,
            "max_results_per_query": self.default_params["num"],
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "supported_features": [
                "date_filtering",
                "site_search",
                "exact_phrase_search",
                "safe_search",
                "language_filtering",
                "geo_location",
            ],
        }

        base_stats.update(google_specific_stats)
        return base_stats
