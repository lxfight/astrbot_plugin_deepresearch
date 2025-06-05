import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever  # 导入注册器
from ..data_models import RetrievedItem


@register_retriever("news")  # 注册为 "news" 类型检索器
class NewsAPIRetriever(BaseRetriever):
    """
    新闻API接口，模拟 NewsAPI.org。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        # self.source_type = "news" # 这一行可以省略，因为注册器装饰器会设置
        self.logger.info("NewsAPIRetriever 模块初始化完成。")

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """
        检查 News API Key 是否存在。
        """
        news_api_key = api_config.get("news_api_key")
        if news_api_key:
            return True
        self.logger.warning("News API Key 未配置，NewsAPIRetriever 将不可用。")
        return False

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行新闻搜索。
        这里我们模拟 NewsAPI。
        """
        news_api_key = api_config.get("news_api_key")

        if not self.check_config_valid(api_config):
            self.logger.error("NewsAPIRetriever 配置无效，无法执行搜索。")
            return []

        search_url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "apiKey": news_api_key,
            "language": "zh",
            "sortBy": "relevancy",
            "pageSize": 5,
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
            self.logger.info(
                f"新闻搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            self.logger.error(
                f"新闻搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
        except Exception as e:
            self.logger.error(
                f"新闻搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )

        return retrieved_items
