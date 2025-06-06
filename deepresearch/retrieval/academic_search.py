import aiohttp
from typing import List, Dict, Any, Set
from datetime import datetime

from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("academic", alias="academic", priority=7)
class AcademicSearchRetriever(BaseRetriever):
    """
    学术检索器实现
    支持 Semantic Scholar API 和 arXiv
    """

    def __init__(self, context, config):
        super().__init__(context, config)
        self.academic_config = config.get("academic_search", {})
        self.api_key = self.academic_config.get("semantic_scholar_api_key", "")
        self.arxiv_enabled = self.academic_config.get("arxiv_enabled", True)
        self.max_papers = self.academic_config.get("max_papers", 15)
        self.rate_limit_per_minute = 60
        self.logger.info("AcademicSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        return {"academic_search_api_key"}

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        api_key = api_config.get("academic_search_api_key", self.api_key)
        # arXiv 可选
        if not api_key and not self.arxiv_enabled:
            self.logger.warning("未配置Semantic Scholar API Key，且未启用arXiv")
            return False
        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        results = []
        # Semantic Scholar
        api_key = api_config.get("academic_search_api_key", self.api_key)
        if api_key:
            results += await self._search_semantic_scholar(query, api_key)
        # arXiv
        if self.arxiv_enabled:
            results += await self._search_arxiv(query)
        filtered_items = self.filter_results(results, min_quality_score=0.3)
        self.logger.info(
            f"学术搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
        )
        return filtered_items

    async def _search_semantic_scholar(
        self, query: str, api_key: str
    ) -> List[RetrievedItem]:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": self.max_papers,
            "fields": "title,abstract,authors,year,url,venue,externalIds",
        }
        headers = {
            "x-api-key": api_key,
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
            async with session.get(url, params=params, **request_kwargs) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self.logger.warning(f"Semantic Scholar API错误: {error_text}")
                    return []
                try:
                    data = await response.json()
                except Exception:
                    return []
        results = []
        for i, item in enumerate(data.get("data", [])):
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            snippet = item.get("abstract", "").strip()
            published_date = None
            if item.get("year"):
                try:
                    published_date = datetime(int(item["year"]), 1, 1)
                except Exception:
                    published_date = None
            if not url or not title:
                continue
            retrieved_item = RetrievedItem(
                url=url,
                title=title,
                snippet=snippet,
                source_type="academic",
                source="semanticscholar",
                published_date=published_date,
                relevance_score=self._calculate_initial_relevance_score(item, query, i),
                raw_source_data=item,
            )
            retrieved_item.metadata = self._extract_metadata(item, i)
            results.append(retrieved_item)
        return results

    async def _search_arxiv(self, query: str) -> List[RetrievedItem]:
        # arXiv API: http://export.arxiv.org/api/query?search_query=all:query&max_results=15
        import xml.etree.ElementTree as ET

        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "max_results": self.max_papers,
        }
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
            async with session.get(url, params=params, **request_kwargs) as response:
                if response.status != 200:
                    return []
                text = await response.text()
        results = []
        try:
            root = ET.fromstring(text)
            for i, entry in enumerate(
                root.findall("{http://www.w3.org/2005/Atom}entry")
            ):
                title = entry.find("{http://www.w3.org/2005/Atom}title").text.strip()
                url = entry.find("{http://www.w3.org/2005/Atom}id").text.strip()
                snippet = entry.find(
                    "{http://www.w3.org/2005/Atom}summary"
                ).text.strip()
                published = entry.find("{http://www.w3.org/2005/Atom}published").text
                published_date = None
                if published:
                    try:
                        published_date = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                    except Exception:
                        published_date = None
                if not url or not title:
                    continue
                retrieved_item = RetrievedItem(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source_type="academic",
                    source="arxiv",
                    published_date=published_date,
                    relevance_score=self._calculate_initial_relevance_score(
                        {}, query, i
                    ),
                    raw_source_data={},
                )
                retrieved_item.metadata = {
                    "rank": i + 1,
                    "search_engine": "arxiv",
                    "published": published,
                }
                results.append(retrieved_item)
        except Exception:
            pass
        return results

    def _calculate_initial_relevance_score(
        self, item: Dict[str, Any], query: str, rank: int
    ) -> float:
        try:
            score = 0.0
            rank_score = max(0, (10 - rank) / 10.0)
            score += rank_score * 0.4
            title = item.get("title", "").lower() if "title" in item else ""
            query_terms = set(query.lower().split())
            title_terms = set(title.split())
            if query_terms and title_terms:
                title_match = len(query_terms & title_terms) / len(query_terms)
                score += title_match * 0.3
            snippet = item.get("abstract", "").lower() if "abstract" in item else ""
            if snippet and query_terms:
                snippet_terms = set(snippet.split())
                snippet_match = len(query_terms & snippet_terms) / len(query_terms)
                score += snippet_match * 0.2
            return min(score, 1.0)
        except Exception:
            return 0.5

    def _extract_metadata(self, item: Dict[str, Any], rank: int) -> Dict[str, Any]:
        metadata = {
            "rank": rank + 1,
            "search_engine": "semanticscholar",
            "venue": item.get("venue", ""),
            "year": item.get("year", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])]
            if "authors" in item
            else [],
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
        return min(score, 1.0)
