# coding: utf-8
import time
import asyncio  # <-- 新增
from typing import Dict, Any
from urllib.parse import quote_plus

import aiohttp

# 捕获 raise_for_status 抛出的异常
from aiohttp import ClientError, ClientResponseError, ClientTimeout  # <-- 新增
from bs4 import BeautifulSoup
from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse
from astrbot.api import logger
from ...core.constants import REQUEST_TIMEOUT_SECONDS

# --- 新增: 超时配置 ---
TIMEOUT_CONFIG = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
# ---------------------


@register_engine
class BingScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取 Bing HTML 页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "bing_scrape"

    @property
    def description(self) -> str:
        return "通过抓取 Bing 搜索页面提供结果，无需API密钥但可能不稳定, 且容易超时或被屏蔽。"

    # __init__ 和 check_config 保持不变
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        search_url = f"https://cn.bing.com/search?q={quote_plus(search_query.query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        }
        logger.info(
            f"[{self.name}] 正在抓取URL: {search_url} (Timeout={REQUEST_TIMEOUT_SECONDS}s)"
        )
        results_list = []

        # --- 修改: session 中加入 timeout ---
        async with aiohttp.ClientSession(
            headers=headers, timeout=TIMEOUT_CONFIG
        ) as session:
            try:
                # 无需在 get 中再设置 timeout
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # --- 修改: 循环逻辑, 先找所有, 再按需截断 ---
                    # Bing 的搜索结果通常包含在 class="b_algo" 的 <li> 标签中
                    all_algo_items = soup.find_all("li", class_="b_algo")
                    for result_item_li in all_algo_items:
                        # --- 检查是否已达到所需数量 ---
                        if len(results_list) >= search_query.count:
                            break
                        # -----------------------------
                        title_tag = result_item_li.select_one("h2 a")
                        # 更精确一点找 snippet, 但保留 find 作为后备
                        snippet_container = result_item_li.select_one(
                            "div.b_caption p"
                        ) or result_item_li.find("div", class_="b_caption")

                        link_url = title_tag.get("href") if title_tag else None

                        if title_tag and link_url and snippet_container:
                            try:
                                result_item = SearchResultItem(
                                    title=title_tag.get_text(strip=True),
                                    link=link_url,  # 直接使用 href, 依赖 Pydantic 验证
                                    snippet=snippet_container.get_text(strip=True),
                                )
                                results_list.append(result_item)
                            except ValidationError as e:
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {link_url}, 错误: {e}"
                                )
                        else:
                            # 如果是因为反爬或结构变化导致 find_all 找到元素但内部结构不对，会走到这里
                            logger.debug(
                                f"[{self.name}] 跳过一个不完整的 li.b_algo 结果项。"
                            )

            # --- 新增: 捕获超时和 HTTP 错误 ---
            except asyncio.TimeoutError:
                logger.error(
                    f"[{self.name}] 抓取超时 ({REQUEST_TIMEOUT_SECONDS}s): {search_url}"
                )
            except ClientResponseError as e:
                # 由 raise_for_status 触发, e.g., 403 Forbidden, 429 Too Many Requests
                logger.error(
                    f"[{self.name}] 抓取时发生 HTTP 错误: 状态码={e.status}, 信息={e.message}, URL={search_url}"
                )
            # --------------------------------
            except ClientError as e:  # 修改为 ClientError
                logger.error(f"[{self.name}] 抓取时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 解析HTML时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()
        logger.info(
            f"[{self.name}] 抓取完成, 共找到 {len(results_list)} 条结果, 耗时 {round(end_time - start_time, 4)} 秒"
        )
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            estimated_total_results=None,
        )
