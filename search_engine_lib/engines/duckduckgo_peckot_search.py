# coding: utf-8
import time
import asyncio
from typing import Dict, Any

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout
from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse
from astrbot.api import logger
from ...core.constants import REQUEST_TIMEOUT_SECONDS

# 超时配置
TIMEOUT_CONFIG = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)


@register_engine
class DuckDuckGoPeckotSearch(BaseSearchEngine):
    """使用Peckot API的DuckDuckGo搜索引擎（备用方案）"""

    @property
    def name(self) -> str:
        return "duckduckgo_peckot"

    @property
    def description(self) -> str:
        return "使用Peckot API的DuckDuckGo搜索，作为官方库的备用方案"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        api_url = "https://api.peckot.com/DuckDuckGoSearch"

        # 限制搜索结果数量在API支持的范围内
        amount = min(max(search_query.count, 1), 50)

        payload = {"keyword": search_query.query, "amount": amount}

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        logger.info(f"[{self.name}] 正在搜索: '{search_query.query}' (amount={amount})")
        results_list = []

        async with aiohttp.ClientSession(timeout=TIMEOUT_CONFIG) as session:
            try:
                async with session.post(
                    api_url, json=payload, headers=headers
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # 检查API响应
                    if data.get("code") != 200:
                        logger.error(
                            f"[{self.name}] API返回错误: {data.get('message', 'Unknown error')}"
                        )
                        if "advice" in data:
                            logger.error(f"[{self.name}] 建议: {data['advice']}")
                        return SearchResponse(
                            query=search_query,
                            engine_name=self.name,
                            results=[],
                            search_time_seconds=round(time.time() - start_time, 4),
                        )

                    # 解析搜索结果
                    results_data = data.get("data", {}).get("results", [])
                    if not results_data:
                        logger.warning(f"[{self.name}] API返回空结果")

                    for item in results_data:
                        try:
                            result_item = SearchResultItem(
                                title=item.get("title", "无标题"),
                                link=item.get("link", ""),
                                snippet=item.get("snippet", "无摘要"),
                            )
                            results_list.append(result_item)
                            logger.debug(
                                f"[{self.name}] 成功解析结果: {result_item.title}"
                            )
                        except ValidationError as e:
                            logger.warning(f"[{self.name}] 过滤掉一条无效结果: {e}")

            except asyncio.TimeoutError:
                logger.error(f"[{self.name}] API请求超时 ({REQUEST_TIMEOUT_SECONDS}s)")
            except ClientResponseError as e:
                logger.error(
                    f"[{self.name}] API请求HTTP错误: 状态码={e.status}, 信息={e.message}"
                )
            except ClientError as e:
                logger.error(f"[{self.name}] API请求网络错误: {e}")
            except Exception as e:
                logger.error(f"[{self.name}] API请求发生未知错误: {e}", exc_info=True)

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
