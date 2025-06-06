from typing import List, Dict
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup
from .. import register_engine
from ..base import BaseSearchEngine

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

    async def check_config(self) -> bool:
        """此引擎不需要特殊配置，因此总是返回 True。"""
        logger.info(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, query: str, count: int = 10) -> List[Dict[str, str]]:
        """使用 aiohttp 获取 HTML 并用 BeautifulSoup 解析。"""
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        logger.info(f"[{self.name}] 正在抓取URL: {search_url}")
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()

                    soup = BeautifulSoup(html, "html.parser")
                    results = []

                    # DuckDuckGo HTML 版本的结果都在 class="result" 的 div 中
                    for result_item in soup.find_all(
                        "div", class_="result", limit=count
                    ):
                        title_tag = result_item.find("a", class_="result__a")
                        snippet_tag = result_item.find("a", class_="result__snippet")

                        if title_tag and snippet_tag:
                            results.append(
                                {
                                    "title": title_tag.get_text(strip=True),
                                    "link": title_tag["href"],
                                    "snippet": snippet_tag.get_text(strip=True),
                                }
                            )

                    logger.info(f"[{self.name}] 抓取并解析到 {len(results)} 条结果。")
                    return results

            except aiohttp.ClientError as e:
                logger.error(f"[{self.name}] 抓取时发生网络错误: {e}")
                return []
            except Exception as e:
                logger.error(f"[{self.name}] 解析HTML时发生未知错误: {e}")
                return []
