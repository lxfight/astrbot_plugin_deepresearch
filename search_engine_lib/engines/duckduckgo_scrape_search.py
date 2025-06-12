import time
import asyncio
from typing import Dict, Any
from urllib.parse import quote_plus

import aiohttp
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
class DuckDuckGoScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取 DuckDuckGo HTML 页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "duckduckgo_scrape"

    @property
    def description(self) -> str:
        return "通过抓取 DuckDuckGo 搜索页面提供结果，无需API密钥但可能不稳定或超时。"

    # __init__ 和 check_config 保持不变
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        base_url = "https://html.duckduckgo.com/html/"
        search_url = f"{base_url}?q={quote_plus(search_query.query)}"
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
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # --- 修改: 循环逻辑, 先找所有, 再按需截断 ---
                    all_result_divs = soup.find_all("div", class_="result")
                    for result_item_div in all_result_divs:
                        # --- 检查是否已达到所需数量 ---
                        if len(results_list) >= search_query.count:
                            break
                        # -----------------------------
                        title_tag = result_item_div.find("a", class_="result__a")
                        snippet_tag = result_item_div.find(
                            "a", class_="result__snippet"
                        )
                        raw_link = title_tag.get("href") if title_tag else None

                        if title_tag and snippet_tag and raw_link:
                            try:
                                # --- 修复: URL 逻辑 ---
                                # DDG html版的 href 通常是绝对 URL 或 // 开头，直接使用，或用 urljoin 处理相对路径
                                # link_url = urljoin(base_url, raw_link)
                                # 更简单: 假定它是绝对路径，让 Pydantic 验证
                                link_url = raw_link
                                # ---------------------

                                result_item = SearchResultItem(
                                    title=title_tag.get_text(strip=True),
                                    link=link_url,  # 使用修复后的 link_url
                                    snippet=snippet_tag.get_text(strip=True),
                                )
                                results_list.append(result_item)
                            except ValidationError as e:
                                # 原始代码的拼接错误会导致所有结果都在这里被捕获
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {raw_link}, 错误: {e}"
                                )
                        else:
                            logger.debug(f"[{self.name}] 跳过一个不完整的 result div。")

            # --- 新增: 捕获超时和 HTTP 错误 ---
            except asyncio.TimeoutError:
                logger.error(
                    f"[{self.name}] 抓取超时 ({REQUEST_TIMEOUT_SECONDS}s): {search_url}"
                )
            except ClientResponseError as e:
                logger.error(
                    f"[{self.name}] 抓取时发生 HTTP 错误: 状态码={e.status}, 信息={e.message}, URL={search_url}"
                )
            # --------------------------------
            except ClientError as e:  # ClientError
                logger.error(f"[{self.name}] 抓取时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 解析HTML时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            # estimated_total_results=None, # SearchResponse 模型定义了默认值None，可省略
        )
