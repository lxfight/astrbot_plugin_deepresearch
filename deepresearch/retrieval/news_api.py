import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.retrieval.base_retriever import BaseRetriever
from deepresearch.data_models import RetrievedItem


class NewsAPIRetriever(BaseRetriever):
    """
    新闻API接口，模拟 NewsAPI.org。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("NewsAPIRetriever 模块初始化完成。")

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行新闻搜索。
        这里我们模拟 NewsAPI。
        """
        news_api_key = api_config.get("news_api_key")

        if not news_api_key:
            logger.warning("未配置 News API Key，使用模拟数据。")
            return self._mock_search_results(query, "news")  # 使用模拟数据

        search_url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": news_api_key,
            "language": "zh",  # 可根据需求调整语言
            "sortBy": "relevancy",
            "pageSize": 5,  # 每次请求获取5条结果
        }

        retrieved_items: List[RetrievedItem] = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    search_url, params=params, timeout=10
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if data.get("status") == "ok" and "articles" in data:
                        for article in data["articles"]:
                            retrieved_items.append(
                                RetrievedItem(
                                    url=article.get("url"),
                                    title=article.get("title"),
                                    snippet=article.get("description"),
                                    source_type="news",
                                )
                            )
            logger.info(
                f"新闻搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            logger.error(
                f"新闻搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(query, "news")
        except Exception as e:
            logger.error(
                f"新闻搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )
            retrieved_items = self._mock_search_results(query, "news")

        return retrieved_items

    def _mock_search_results(self, query: str, source_type: str) -> List[RetrievedItem]:
        """模拟搜索结果，与WebSearchRetriever共享，但为了清晰分开"""
        logger.warning(f"正在为 '{query}' 提供模拟 {source_type} 搜索结果。")
        mock_data = [
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/article1?q={query}",
                title=f"模拟 {source_type} 文章 - {query} 1",
                snippet=f"这是关于 '{query}' 的第一篇模拟新闻文章摘要。",
                source_type=source_type,
            ),
            RetrievedItem(
                url=f"https://mock.example.com/{source_type}/article2?q={query}",
                title=f"模拟 {source_type} 文章 - {query} 2",
                snippet=f"这是关于 '{query}' 的第二篇模拟新闻文章摘要。",
                source_type=source_type,
            ),
        ]
        return mock_data
