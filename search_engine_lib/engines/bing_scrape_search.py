# coding: utf-8
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
class BingScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取 Bing HTML 页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "bing_scrape"

    @property
    def description(self) -> str:
        return "通过抓取 Bing 搜索页面提供结果，无需API密钥但可能不稳定。"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        """此引擎不需要特殊配置，因此总是返回 True。"""
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        """使用 aiohttp 获取 Bing HTML 并用 BeautifulSoup 解析，返回标准化的 SearchResponse 对象。"""
        start_time = time.time()

        # Bing 搜索 URL，使用 quote_plus 对查询参数进行编码
        search_url = f"https://cn.bing.com/search?q={quote_plus(search_query.query)}"

        # 伪造浏览器 Headers 以避免被屏蔽
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        }

        logger.info(f"[{self.name}] 正在抓取URL: {search_url}")

        results_list = []

        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(search_url) as response:
                    response.raise_for_status()  # 如果状态码不是 2xx，则抛出异常
                    html = await response.text()

                    soup = BeautifulSoup(html, "html.parser")

                    # Bing 的搜索结果通常包含在 class="b_algo" 的 <li> 标签中
                    # 使用 limit 参数来限制解析结果的数量，与查询保持一致
                    for result_item_li in soup.find_all(
                        "li", class_="b_algo", limit=search_query.count
                    ):
                        # 提取标题和链接，它们通常在 <h2><a>...</a></h2> 结构中
                        title_tag = result_item_li.select_one("h2 a")

                        # 提取摘要，它通常在 <div class="b_caption"> 中
                        snippet_container = result_item_li.find(
                            "div", class_="b_caption"
                        )

                        if title_tag and title_tag.get("href") and snippet_container:
                            try:
                                # Bing 的链接通常是绝对路径，直接使用即可
                                link_url = title_tag["href"]

                                # 使用 Pydantic 模型进行验证和数据清洗
                                result_item = SearchResultItem(
                                    title=title_tag.get_text(strip=True),
                                    link=link_url,
                                    snippet=snippet_container.get_text(strip=True),
                                )
                                results_list.append(result_item)
                            except ValidationError as e:
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {title_tag.get('href')}, 错误: {e}"
                                )
                        else:
                            logger.debug(
                                f"[{self.name}] 跳过一个不完整的 li.b_algo 结果项。"
                            )

            except aiohttp.ClientError as e:
                logger.error(f"[{self.name}] 抓取时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 解析HTML时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()

        # 构建并返回标准的 SearchResponse 对象
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            estimated_total_results=None,  # 抓取方式难以稳定获取总数
        )
