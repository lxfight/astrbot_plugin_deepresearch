import aiohttp
from typing import List, Dict, Any, Set

from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("web", alias="duckduckgo", priority=6)
class DuckDuckGoSearchRetriever(BaseRetriever):
    """
    DuckDuckGo 搜索检索器实现
    使用 DuckDuckGo 非官方 API 进行网页搜索
    """

    def __init__(self, context, config):
        super().__init__(context, config)
        self.endpoint = "https://duckduckgo.com/html/"
        self.max_results = min(self.max_results_per_engine, 10)
        self.rate_limit_per_minute = 60
        self.logger.info("DuckDuckGoSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        return set()

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        # DuckDuckGo 不需要API Key
        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        if not query.strip():
            return []
        try:
            params = {
                "q": query,
                "kl": "cn-zh",
                "s": "0",
            }
            results = await self._execute_search_request(params)
            retrieved_items = self._parse_search_results(results, query)
            filtered_items = self.filter_results(retrieved_items, min_quality_score=0.3)
            self.logger.info(
                f"DuckDuckGo搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
            )
            return filtered_items
        except Exception as e:
            self.logger.error(f"DuckDuckGo搜索出错: {e}", exc_info=True)
            return []

    async def _execute_search_request(self, params: Dict[str, Any]) -> str:
        headers = {
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
                self.endpoint, data=params, **request_kwargs
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"DuckDuckGo返回错误 {response.status}: {error_text}"
                    )
                text = await response.text()
                return text

    def _parse_search_results(self, html: str, query: str) -> List[RetrievedItem]:
        import re

        results = []
        # DuckDuckGo HTML结果解析
        pattern = re.compile(
            r'<a rel="nofollow" class="result__a" href="([^"]+)".*?>(.*?)</a>', re.S
        )
        matches = pattern.findall(html)
        for i, (url, title) in enumerate(matches[: self.max_results]):
            title_text = re.sub(r"<.*?>", "", title)
            snippet = ""  # DuckDuckGo HTML接口不直接提供摘要
            retrieved_item = RetrievedItem(
                url=url,
                title=title_text,
                snippet=snippet,
                source_type="web",
                source="duckduckgo",
                published_date=None,
                relevance_score=self._calculate_initial_relevance_score(
                    title_text, query, i
                ),
                raw_source_data={"url": url, "title": title_text},
            )
            retrieved_item.metadata = {
                "rank": i + 1,
                "search_engine": "duckduckgo",
            }
            results.append(retrieved_item)
        return results

    def _calculate_initial_relevance_score(
        self, title: str, query: str, rank: int
    ) -> float:
        try:
            score = 0.0
            rank_score = max(0, (10 - rank) / 10.0)
            score += rank_score * 0.4
            query_terms = set(query.lower().split())
            title_terms = set(title.lower().split())
            if query_terms and title_terms:
                title_match = len(query_terms & title_terms) / len(query_terms)
                score += title_match * 0.3
            return min(score, 1.0)
        except Exception:
            return 0.5

    def _calculate_quality_score(self, result: RetrievedItem) -> float:
        score = super()._calculate_quality_score(result)
        if result.metadata:
            rank = result.metadata.get("rank", 11)
            if rank <= 3:
                score += 0.2
            elif rank <= 5:
                score += 0.1
        return min(score, 1.0)
