# coding: utf-8
import time
import asyncio
from typing import Dict, Any

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse
from astrbot.api import logger

@register_engine
class DuckDuckGoAPISearch(BaseSearchEngine):
    """使用官方DuckDuckGo搜索库进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "duckduckgo_api"

    @property
    def description(self) -> str:
        return "使用官方DuckDuckGo搜索库，隐私友好且稳定。"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get("timeout", 10.0)

    async def check_config(self) -> bool:
        if not DDGS_AVAILABLE:
            logger.error(f"[{self.name}] DuckDuckGo搜索库未安装。请运行: pip install duckduckgo-search")
            return False
        logger.debug(f"[{self.name}] 配置检查通过。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        if not DDGS_AVAILABLE:
            logger.error(f"[{self.name}] DuckDuckGo搜索库未安装。")
            return SearchResponse(
                query=search_query,
                engine_name=self.name,
                results=[],
                search_time_seconds=0.0,
            )

        start_time = time.time()
        logger.info(f"[{self.name}] 正在搜索: '{search_query.query}' (count={search_query.count})")
        results_list = []

        try:
            # 使用异步执行器运行同步的DDGS搜索
            loop = asyncio.get_event_loop()
            ddgs_results = await loop.run_in_executor(
                None, 
                self._search_sync, 
                search_query.query, 
                search_query.count
            )

            for item in ddgs_results:
                try:
                    result_item = SearchResultItem(
                        title=item.get("title", "无标题"),
                        link=item.get("href", ""),
                        snippet=item.get("body", "无摘要"),
                    )
                    results_list.append(result_item)
                    logger.debug(f"[{self.name}] 成功解析结果: {result_item.title}")
                except ValidationError as e:
                    logger.warning(f"[{self.name}] 过滤掉一条无效结果: {e}")

        except Exception as e:
            logger.error(f"[{self.name}] 搜索时发生错误: {e}", exc_info=True)

        end_time = time.time()
        logger.info(
            f"[{self.name}] 搜索完成, 共找到 {len(results_list)} 条结果, 耗时 {round(end_time - start_time, 4)} 秒"
        )
        
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            estimated_total_results=None,
        )

    def _search_sync(self, query: str, max_results: int) -> list:
        """同步搜索方法，在执行器中运行"""
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query, 
                    max_results=max_results,
                    region='wt-wt',  # 全球结果
                    safesearch='moderate',
                    timelimit=None
                ))
                return results
        except Exception as e:
            logger.error(f"[{self.name}] DDGS同步搜索错误: {e}")
            return []
