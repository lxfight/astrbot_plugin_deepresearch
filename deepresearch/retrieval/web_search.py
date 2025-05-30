import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.retrieval.base_retriever import BaseRetriever
from deepresearch.data_models import RetrievedItem


class WebSearchRetriever(BaseRetriever):
    """
    通用搜索引擎接口，模拟 Google Custom Search 或 DuckDuckGo Instant Answer。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("WebSearchRetriever 模块初始化完成。")

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行网页搜索。
        这里我们模拟 Google Custom Search API。
        """
        google_cse_api_key = api_config.get("google_cse_api_key")
        google_cse_cx = api_config.get("google_cse_cx")

        if not google_cse_api_key or not google_cse_cx:
            logger.warning(
                "未配置 Google Custom Search API Key 或 CX，使用模拟数据。"
            )
            return self._mock_search_results(query, "web")  # 使用模拟数据

        search_url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": google_cse_api_key,
            "cx": google_cse_cx,
            "q": query,
            "num": 5,  # 每次请求获取5条结果
        }

        retrieved_items: List[RetrievedItem] = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    search_url, params=params, timeout=10
                ) as response:
                    response.raise_for_status()  # 检查HTTP响应状态
                    data = await response.json()

                    if "items" in data:
                        for item in data["items"]:
                            retrieved_items.append(
                                RetrievedItem(
                                    url=item.get("link"),
                                    title=item.get("title"),
                                    snippet=item.get("snippet"),
                                    source_type="web",
                                )
                            )
            logger.info(
                f"网页搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"网页搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(
                query, "web"
            )  # 失败时仍提供模拟数据
        except Exception as e:
            logger.error(
                f"网页搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(query, "web")

        return retrieved_items

    def _mock_search_results(self, query: str, source_type: str) -> List[RetrievedItem]:
        """模拟搜索结果"""
        logger.warning(f"正在为 '{query}' 提供模拟 {source_type} 搜索结果。")
        mock_data = [
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/result1?q={query}",
                title=f"模拟 {source_type} 结果 - {query} 1",
                snippet=f"这是关于 '{query}' 的第一个模拟搜索结果摘要。",
                source_type=source_type,
            ),
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/result2?q={query}",
                title=f"模拟 {source_type} 结果 - {query} 2",
                snippet=f"这是关于 '{query}' 的第二个模拟搜索结果摘要。",
                source_type=source_type,
            ),
        ]
        return mock_data
