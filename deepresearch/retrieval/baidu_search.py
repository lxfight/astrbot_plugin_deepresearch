import aiohttp
from typing import List, Dict, Any, Set
from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("web", alias="baidu", priority=7)
class BaiduSearchRetriever(BaseRetriever):
    """
    百度搜索API 检索器实现
    使用百度开放平台API进行网页搜索
    """

    def __init__(self, context, config):
        super().__init__(context, config)
        self.baidu_config = config.get("baidu_search", {})
        self.api_key = self.baidu_config.get("api_key", "")
        self.secret_key = self.baidu_config.get("secret_key", "")
        self.endpoint = "https://api.baidu.com/json/tongji/v1/ReportService/search"
        self.default_params = {
            "rn": min(self.max_results_per_engine, 10),
            "pn": 0,
        }
        self.rate_limit_per_minute = 100
        self.logger.info("BaiduSearchRetriever 模块初始化完成")

    def get_required_config_keys(self) -> Set[str]:
        return {"baidu_api_key", "baidu_secret_key"}

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        api_key = api_config.get("baidu_api_key", self.api_key)
        secret_key = api_config.get("baidu_secret_key", self.secret_key)
        if not api_key or not secret_key:
            self.logger.warning("Baidu API Key 或 Secret Key 未配置")
            return False
        if len(api_key) < 10 or len(secret_key) < 10:
            self.logger.warning("Baidu API Key 或 Secret Key 格式可能不正确")
            return False
        return True

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        if not query.strip():
            return []
        api_key = api_config.get("baidu_api_key", self.api_key)
        secret_key = api_config.get("baidu_secret_key", self.secret_key)
        if not self.check_config_valid(api_config):
            self.logger.error("Baidu搜索配置无效，无法执行搜索")
            return []
        try:
            params = self.default_params.copy()
            params.update({"wd": query})
            results = await self._execute_search_request(api_key, secret_key, params)
            retrieved_items = self._parse_search_results(results, query)
            filtered_items = self.filter_results(retrieved_items, min_quality_score=0.3)
            self.logger.info(
                f"Baidu搜索 '{query}' 完成，获得 {len(filtered_items)} 个质量结果"
            )
            return filtered_items
        except Exception as e:
            self.logger.error(f"Baidu搜索出错: {e}", exc_info=True)
            return []

    async def _execute_search_request(
        self, api_key: str, secret_key: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }
        # 百度API通常需要OAuth2鉴权，这里仅作示例，实际需根据API文档实现
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
            # 这里只是示例，实际API参数和鉴权方式需查阅百度开放平台文档
            async with session.get(
                "https://www.baidu.com/s",
                params={"wd": params["wd"], "rn": params["rn"]},
                **request_kwargs,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Baidu搜索API返回错误 {response.status}: {error_text}"
                    )
                text = await response.text()
                # 简单HTML解析，实际生产建议用官方API
                import re

                pattern = re.compile(
                    r'<a.*?href="(http[s]?://[^"]+)".*?>(.*?)</a>', re.S
                )
                matches = pattern.findall(text)
                results = []
                for i, (url, title) in enumerate(matches[: params["rn"]]):
                    results.append(
                        {
                            "title": re.sub(r"<.*?>", "", title),
                            "url": url,
                            "snippet": "",
                        }
                    )
                return {"results": results}

    def _parse_search_results(
        self, data: Dict[str, Any], query: str
    ) -> List[RetrievedItem]:
        results = []
        try:
            web_results = data.get("results", [])
            for i, item in enumerate(web_results):
                title = item.get("title", "").strip()
                url = item.get("url", "").strip()
                snippet = item.get("snippet", "").strip()
                if not url or not title:
                    continue
                retrieved_item = RetrievedItem(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source_type="web",
                    source="baidu",
                    published_date=None,
                    relevance_score=self._calculate_initial_relevance_score(
                        item, query, i
                    ),
                    raw_source_data=item,
                )
                retrieved_item.metadata = self._extract_metadata(item, i)
                results.append(retrieved_item)
            self.logger.debug(f"Baidu搜索解析了 {len(results)} 个结果")
        except Exception as e:
            self.logger.error(f"解析Baidu搜索结果时出错: {e}", exc_info=True)
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
            "search_engine": "baidu",
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
