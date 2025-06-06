import time
from typing import Dict, Any
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup
from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse
from astrbot.api import logger


@register_engine
class DuckDuckGoScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取 DuckDuckGo HTML 页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "duckduckgo_scrape"

    @property
    def description(self) -> str:
        return "通过抓取 DuckDuckGo 搜索页面提供结果，无需API密钥但可能不稳定。"

    def __init__(self, config: Dict[str, Any]):
        # 调用父类构造函数，尽管这个引擎目前不使用配置
        super().__init__(config)

    async def check_config(self) -> bool:
        """此引擎不需要特殊配置，因此总是返回 True。"""
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        """使用 aiohttp 获取 HTML 并用 BeautifulSoup 解析，返回标准化的 SearchResponse 对象。"""
        start_time = time.time()

        # DuckDuckGo HTML 版本的 URL
        search_url = (
            f"https://html.duckduckgo.com/html/?q={quote_plus(search_query.query)}"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        }

        logger.info(f"[{self.name}] 正在抓取URL: {search_url}")

        results_list = []

        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()

                    soup = BeautifulSoup(html, "html.parser")

                    # DuckDuckGo HTML 版本的结果都在 class="result" 的 div 中
                    # 使用 limit 参数来控制获取数量
                    for result_item_div in soup.find_all(
                        "div", class_="result", limit=search_query.count
                    ):
                        title_tag = result_item_div.find("a", class_="result__a")
                        snippet_tag = result_item_div.find(
                            "a", class_="result__snippet"
                        )

                        if title_tag and snippet_tag and title_tag.get("href"):
                            try:
                                # DDG 的链接是相对的，需要拼接
                                link_url = f"https://duckduckgo.com{title_tag['href']}"

                                result_item = SearchResultItem(
                                    title=title_tag.get_text(strip=True),
                                    link=link_url,
                                    snippet=snippet_tag.get_text(strip=True),
                                )
                                results_list.append(result_item)
                            except ValidationError as e:
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {title_tag.get('href')}, 错误: {e}"
                                )
                        else:
                            logger.debug(f"[{self.name}] 跳过一个不完整的 result div。")

            except aiohttp.ClientError as e:
                logger.error(f"[{self.name}] 抓取时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 解析HTML时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()

        # 构建并返回标准的 SearchResponse 对象
        # 注意：此引擎无法获取 estimated_total_results，所以该字段为 None
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
        )
