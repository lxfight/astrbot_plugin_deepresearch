import aiohttp
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.retrieval.base_retriever import BaseRetriever
from deepresearch.retrieval.retriever_registry import register_retriever  # 导入注册器
from deepresearch.data_models import RetrievedItem


@register_retriever("academic")  # 注册为 "academic" 类型检索器
class AcademicSearchRetriever(BaseRetriever):
    """
    学术搜索引擎接口，模拟 Semantic Scholar API 或 ArXiv API。
    实际使用时，你需要注册并使用真实的API。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        # self.source_type = "academic" # 这一行可以省略，因为注册器装饰器会设置
        self.logger.info("AcademicSearchRetriever 模块初始化完成。")

    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """
        检查 Academic Search API Key 是否存在 (如果需要)。
        对于 Semantic Scholar 免费 API，可能不需要 API Key。
        这里假设即使没有 key 也可以工作（或者你可能需要提供一个虚拟的key）。
        """
        # academic_api_key = api_config.get("academic_search_api_key")
        # return bool(academic_api_key) # 如果需要API Key
        return True  # Semantic Scholar 默认是开放的，只要网络通畅即可

    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        执行学术文献搜索。
        这里我们模拟 Semantic Scholar API。
        """
        academic_api_key = api_config.get("academic_search_api_key")

        if not self.check_config_valid(api_config):
            self.logger.error("AcademicSearchRetriever 配置无效，无法执行搜索。")
            return []

        search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {"query": query, "fields": "url,title,abstract", "limit": 5}
        headers = {}
        if academic_api_key:  # 如果配置了API Key，则加上
            headers["x-api-key"] = academic_api_key

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
            self.logger.info(
                f"学术搜索 '{query}' 成功，获得 {len(retrieved_items)} 条结果。"
            )
        except aiohttp.ClientError as e:
            self.logger.error(
                f"学术搜索 API 请求失败 for query '{query}': {e}", exc_info=True
            )
        except Exception as e:
            self.logger.error(
                f"学术搜索处理结果失败 for query '{query}': {e}", exc_info=True
            )

        return retrieved_items
