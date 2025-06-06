import aiohttp
from typing import List, Dict, Any, Set
import json

from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("web", alias="serper", priority=8)
class SerperSearchRetriever(BaseRetriever):
    """
    Serper.dev API 检索器实现
    使用 Serper.dev 提供的 Google 搜索结果
    """

    def __init__(self, context, config):
        super().__init__(context, config)
        self.serper_config = config.get("serper_search", {})
        self.api_key = self.serper_config.get("api_key", "")
        self.endpoint = "https://google.serper.dev/search"
        self.default_params = {
            "num": min(self.max_results_per_engine, 10),
            "gl": "cn",
            "hl": "zh",
        }
        self.rate_limit_per_minute = 100
        self.logger.info("SerperSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        return {"serper_api_key"}

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        api_key = api_config.get("serper_api_key", self.api_key)
        if not api_key or len(api_key) < 20:
            self.logger.warning("Serper API Key 未配置或格式不正确")
            return False
        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        if not query.strip():
            return []
        api_key = api_config.get("serper_api_key", self.api_key)
        if not self.check_config_valid(api_config):
            self.logger.error("Serper搜索配置无效，无法执行搜索")
            return []
        try:
            params = self.default_params.copy()
            params.update({"q": query})
            results = await self._execute_search_request(api_key, params)
            retrieved_items = self._parse_search_results(results, query)
            filtered_items = self.filter_results(retrieved_items, min_quality_score=0.3)
            self.logger.info(
                f"Serper搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
            )
            return filtered_items
        except Exception as e:
            self.logger.error(f"Serper搜索出错: {e}", exc_info=True)
            return []

    async def _execute_search_request(
        self, api_key: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
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
            async with session.post(
                self.endpoint, json=params, **request_kwargs
            ) as response:
                if response.status == 429:
                    raise Exception("Serper搜索API配额已用完或请求过于频繁")
                elif response.status == 401:
                    raise Exception("Serper搜索API访问被拒绝，请检查API Key")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Serper搜索API返回错误 {response.status}: {error_text}"
                    )
                try:
                    data = await response.json()
                    return data
                except json.JSONDecodeError as e:
                    raise Exception(f"Serper搜索API返回无效JSON: {e}")

    def _parse_search_results(
        self, data: Dict[str, Any], query: str
    ) -> List[RetrievedItem]:
        results = []
        try:
            web_results = data.get("organic", [])
            for i, item in enumerate(web_results):
                title = item.get("title", "").strip()
                url = item.get("link", "").strip()
                snippet = item.get("snippet", "").strip()
                if not url or not title:
                    continue
                retrieved_item = RetrievedItem(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source_type="web",
                    source="serper",
                    published_date=None,
                    relevance_score=self._calculate_initial_relevance_score(
                        item, query, i
                    ),
                    raw_source_data=item,
                )
                retrieved_item.metadata = self._extract_metadata(item, i)
                results.append(retrieved_item)
            self.logger.debug(f"Serper搜索解析了 {len(results)} 个结果")
        except Exception as e:
            self.logger.error(f"解析Serper搜索结果时出错: {e}", exc_info=True)
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
            snippet = item.get("snippet", "").lower()
            if snippet and query_terms:
                snippet_terms = set(snippet.split())
                snippet_match = len(query_terms & snippet_terms) / len(query_terms)
                score += snippet_match * 0.2
            url = item.get("link", "")
            if url:
                domain_score = self._evaluate_domain_credibility(url)
                score += domain_score * 0.1
            return min(score, 1.0)
        except Exception:
            return 0.5

    def _extract_metadata(self, item: Dict[str, Any], rank: int) -> Dict[str, Any]:
        metadata = {
            "rank": rank + 1,
            "search_engine": "serper",
            "snippet": item.get("snippet", ""),
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
                "github.com",
                "stackoverflow.com",
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
