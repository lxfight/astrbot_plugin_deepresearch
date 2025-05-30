import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.retrieval.base_retriever import BaseRetriever
from deepresearch.data_models import RetrievedItem


class AcademicSearchRetriever(BaseRetriever):
    """
    学术搜索引擎接口，模拟 Semantic Scholar API 或 ArXiv API。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("AcademicSearchRetriever 模块初始化完成。")

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行学术文献搜索。
        这里我们模拟 Semantic Scholar API。
        """
        academic_api_key = api_config.get(
            "academic_search_api_key"
        )  # Semantic Scholar API 可能不需要 key

        if not academic_api_key:
            logger.warning("未配置学术搜索 API Key，使用模拟数据。")
            return self._mock_search_results(query, "academic")  # 使用模拟数据

        # Semantic Scholar API 示例：https://api.semanticscholar.org/graph/v1/paper/search
        search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "fields": "url,title,abstract",  # 请求返回的字段
            "limit": 5,  # 每次请求获取5条结果
        }
        headers = {
            "x-api-key": academic_api_key  # 如果需要API Key
        }

        retrieved_items: List[RetrievedItem] = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    search_url, params=params, headers=headers, timeout=10
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "data" in data:
                        for paper in data["data"]:
                            retrieved_items.append(
                                RetrievedItem(
                                    url=paper.get("url"),
                                    title=paper.get("title"),
                                    snippet=paper.get("abstract"),
                                    source_type="academic",
                                )
                            )
            logger.info(
                f"学术搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"学术搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(query, "academic")
        except Exception as e:
            logger.error(
                f"学术搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(query, "academic")

        return retrieved_items

    def _mock_search_results(self, query: str, source_type: str) -> List[RetrievedItem]:
        """模拟搜索结果，与WebSearchRetriever共享，但为了清晰分开"""
        logger.warning(f"正在为 '{query}' 提供模拟 {source_type} 搜索结果。")
        mock_data = [
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/paper1?q={query}",
                title=f"模拟 {source_type} 论文 - {query} I",
                snippet=f"这是关于 '{query}' 的第一篇模拟学术论文摘要。",
                source_type=source_type,
            ),
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/paper2?q={query}",
                title=f"模拟 {source_type} 论文 - {query} II",
                snippet=f"这是关于 '{query}' 的第二篇模拟学术论文摘要。",
                source_type=source_type,
            ),
        ]
        return mock_data
