import aiohttp
from typing import List, Dict, Any, Set
import json
from datetime import datetime, timedelta

from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("news", alias="news", priority=7)
class NewsSearchRetriever(BaseRetriever):
    """
    NewsAPI 新闻检索器实现
    使用 NewsAPI 检索新闻内容
    """

    def __init__(self, context, config):
        super().__init__(context, config)
        self.news_config = config.get("news_search", {})
        self.api_key = self.news_config.get("news_api_key", "")
        self.endpoint = "https://newsapi.org/v2/everything"
        self.days_range = self.news_config.get("days_range", 30)
        self.max_articles = self.news_config.get("max_articles", 20)
        self.rate_limit_per_minute = 60
        self.logger.info("NewsSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        return {"news_api_key"}

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        api_key = api_config.get("news_api_key", self.api_key)
        if not api_key or len(api_key) < 10:
            self.logger.warning("NewsAPI Key 未配置或格式不正确")
            return False
        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        if not query.strip():
            return []
        api_key = api_config.get("news_api_key", self.api_key)
        if not self.check_config_valid(api_config):
            self.logger.error("NewsAPI 配置无效，无法执行新闻搜索")
            return []
        try:
            params = {
                "q": query,
                "language": "zh",
                "pageSize": min(self.max_articles, 100),
                "sortBy": "publishedAt",
            }
            if self.days_range > 0:
                from_date = (
                    datetime.utcnow() - timedelta(days=self.days_range)
                ).strftime("%Y-%m-%d")
                params["from"] = from_date
            results = await self._execute_search_request(api_key, params)
            retrieved_items = self._parse_search_results(results, query)
            filtered_items = self.filter_results(retrieved_items, min_quality_score=0.3)
            self.logger.info(
                f"NewsAPI新闻搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
            )
            return filtered_items
        except Exception as e:
            self.logger.error(f"NewsAPI新闻搜索出错: {e}", exc_info=True)
            return []

    async def _execute_search_request(
        self, api_key: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        headers = {
            "X-Api-Key": api_key,
            "User-Agent": self.user_agent,
        }
        connector_kwargs = {}
        if self.enable_proxy and self.proxy_url:
            connector_kwargs["connector"] = aiohttp.TCPConnector(
                limit=100, ttl_dns_cache=300
            )
        timeout = aiohttp.ClientTimeout(total=self.search_timeout)
        async with aiohttp.ClientSession(
            headers=headers, timeout=timeout, **connector_kwargs
        ) as session:
            request_kwargs = {}
            if self.enable_proxy and self.proxy_url:
                request_kwargs["proxy"] = self.proxy_url
            async with session.get(
                self.endpoint, params=params, **request_kwargs
            ) as response:
                if response.status == 429:
                    raise Exception("NewsAPI配额已用完或请求过于频繁")
                elif response.status == 401:
                    raise Exception("NewsAPI访问被拒绝，请检查API Key")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"NewsAPI返回错误 {response.status}: {error_text}")
                try:
                    data = await response.json()
                    return data
                except json.JSONDecodeError as e:
                    raise Exception(f"NewsAPI返回无效JSON: {e}")

    def _parse_search_results(
        self, data: Dict[str, Any], query: str
    ) -> List[RetrievedItem]:
        results = []
        try:
            articles = data.get("articles", [])
            for i, item in enumerate(articles):
                title = item.get("title", "").strip()
                url = item.get("url", "").strip()
                snippet = item.get("description", "").strip()
                published_at = item.get("publishedAt")
                published_date = None
                if published_at:
                    try:
                        published_date = datetime.fromisoformat(
                            published_at.replace("Z", "+00:00")
                        )
                    except Exception:
                        published_date = None
                if not url or not title:
                    continue
                retrieved_item = RetrievedItem(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source_type="news",
                    source="newsapi",
                    published_date=published_date,
                    relevance_score=self._calculate_initial_relevance_score(
                        item, query, i
                    ),
                    raw_source_data=item,
                )
                retrieved_item.metadata = self._extract_metadata(item, i)
                results.append(retrieved_item)
            self.logger.debug(f"NewsAPI解析了 {len(results)} 个新闻结果")
        except Exception as e:
            self.logger.error(f"解析NewsAPI新闻结果时出错: {e}", exc_info=True)
        return results

    def _calculate_initial_relevance_score(
        self, item: Dict[str, Any], query: str, rank: int
    ) -> float:
        try:
            score = 0.0
            rank_score = max(0, (10 - rank) / 10.0)
            score += rank_score * 0.4
            title = item.get("title", "").lower()
            query_terms = set(query.lower().split())
            title_terms = set(title.split())
            if query_terms and title_terms:
                title_match = len(query_terms & title_terms) / len(query_terms)
                score += title_match * 0.3
            snippet = item.get("description", "").lower()
            if snippet and query_terms:
                snippet_terms = set(snippet.split())
                snippet_match = len(query_terms & snippet_terms) / len(query_terms)
                score += snippet_match * 0.2
            url = item.get("url", "")
            if url:
                domain_score = self._evaluate_domain_credibility(url)
                score += domain_score * 0.1
            return min(score, 1.0)
        except Exception:
            return 0.5

    def _extract_metadata(self, item: Dict[str, Any], rank: int) -> Dict[str, Any]:
        metadata = {
            "rank": rank + 1,
            "search_engine": "newsapi",
            "source_name": item.get("source", {}).get("name", ""),
            "author": item.get("author", ""),
            "published_at": item.get("publishedAt", ""),
        }
        return metadata

    def _calculate_quality_score(self, result: RetrievedItem) -> float:
        score = super()._calculate_quality_score(result)
        if result.metadata:
            rank = result.metadata.get("rank", 11)
            if rank <= 3:
                score += 0.2
            elif rank <= 5:
                score += 0.1
        if result.url:
            domain_score = self._evaluate_domain_credibility(result.url)
            score += domain_score * 0.1
        return min(score, 1.0)

    def _evaluate_domain_credibility(self, url: str) -> float:
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.lower()
            trusted_domains = {
                "gov.cn",
                "edu.cn",
                "wikipedia.org",
                "bbc.com",
                "reuters.com",
                "nature.com",
                "xinhuanet.com",
                "people.com.cn",
            }
            for trusted in trusted_domains:
                if trusted in domain:
                    return 1.0
            if any(ind in domain for ind in [".gov.", ".edu.", ".org."]):
                return 0.8
            elif any(ind in domain for ind in [".com.", ".net.", ".cn"]):
                return 0.6
            else:
                return 0.4
        except Exception:
            return 0.5
