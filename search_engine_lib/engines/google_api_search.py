import time
from typing import Dict, Any

import aiohttp
from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse

from astrbot.api import logger


@register_engine
class GoogleApiSearch(BaseSearchEngine):
    """使用 Google Custom Search JSON API 进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "google_api"

    @property
    def description(self) -> str:
        return "通过 Google Custom Search API 提供搜索结果，稳定可靠。"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        engine_config = self.config.get(self.name, {})
        logger.debug(f"[{self.name}] 初始化引擎配置: {engine_config}")
        self.api_key = engine_config.get("api_key")
        self.cse_id = engine_config.get("cse_id")
        self.api_url = "https://www.googleapis.com/customsearch/v1"

    async def check_config(self) -> bool:
        """检查 API Key 和 CSE ID 是否已配置。"""
        if not self.api_key or self.api_key == "你的Google-API-Key":
            logger.warning(f"[{self.name}] 注册失败：缺少或未配置 'api_key'。")
            return False
        if not self.cse_id or self.cse_id == "你的Google-CSE-ID":
            logger.warning(f"[{self.name}] 注册失败：缺少或未配置 'cse_id'。")
            return False

        logger.debug(f"[{self.name}] 配置检查通过。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        """使用 aiohttp 异步请求 Google API，并返回标准化的 SearchResponse 对象。"""
        start_time = time.time()

        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": search_query.query,
            "num": search_query.count,
        }

        logger.info(f"[{self.name}] 正在搜索关键词: '{search_query.query}'")

        results_list = []
        estimated_total = None

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.api_url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "error" in data:
                        error_msg = data["error"].get("message", "未知API错误")
                        logger.error(f"[{self.name}] Google API 返回错误: {error_msg}")

                    # Google API 提供了估算总数
                    if (
                        "searchInformation" in data
                        and "totalResults" in data["searchInformation"]
                    ):
                        estimated_total = int(data["searchInformation"]["totalResults"])

                    for item in data.get("items", []):
                        try:
                            # 使用 Pydantic 模型来验证和创建结果项
                            # 如果 link 或其他字段不符合模型要求（如不是有效URL），会抛出 ValidationError
                            result_item = SearchResultItem(
                                title=item.get("title", "无标题"),
                                link=item.get("link", ""),
                                snippet=item.get("snippet", "无摘要"),
                            )
                            results_list.append(result_item)
                        except ValidationError as e:
                            logger.warning(
                                f"[{self.name}] 过滤掉一条来自API的无效结果。数据: {item}，错误: {e}"
                            )

            except aiohttp.ClientError as e:
                logger.error(f"[{self.name}] 请求API时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 处理API响应时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()

        # 构建并返回标准的 SearchResponse 对象
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            estimated_total_results=estimated_total,
        )
