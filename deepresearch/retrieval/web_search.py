import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, AstrBotConfig
from .base_retriever import BaseRetriever
from .retriever_registry import register_retriever
from ..data_models import RetrievedItem


@register_retriever("web")  # 注册为 "web" 类型检索器
class WebSearchRetriever(BaseRetriever):
    """
    通用搜索引擎接口，模拟 Google Custom Search 或 DuckDuckGo Instant Answer。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        # self.source_type = "web" # 这一行可以省略，因为注册器装饰器会设置
        self.logger.info("WebSearchRetriever 模块初始化完成。")

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """
        检查 Google Custom Search API Key 和 CX 是否存在。
        """
        google_cse_api_key = api_config.get("google_cse_api_key")
        google_cse_cx = api_config.get("google_cse_cx")
        if google_cse_api_key and google_cse_cx:
            return True
        self.logger.warning(
            "Google Custom Search API Key 或 CX 未配置，WebSearchRetriever 将不可用。"
        )
        return False

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行网页搜索。
        这里我们模拟 Google Custom Search API。
        """
        google_cse_api_key = api_config.get("google_cse_api_key")
        google_cse_cx = api_config.get("google_cse_cx")

        # 再次检查配置，以防在工厂层面跳过但仍被调用（虽然工厂会避免这种情况）
        if not self.check_config_valid(api_config):
            self.logger.error("WebSearchRetriever 配置无效，无法执行搜索。")
            return []  # 或者抛出异常

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
            self.logger.info(
                f"网页搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            self.logger.error(
                f"网页搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
        except Exception as e:
            self.logger.error(
                f"网页搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )

        return retrieved_items
