# coding: utf-8
import time
import asyncio
from typing import Dict, Any
from urllib.parse import quote_plus

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout
from bs4 import BeautifulSoup
from pydantic import ValidationError

from .. import register_engine
from ..base import BaseSearchEngine
from ..models import SearchQuery, SearchResultItem, SearchResponse
from astrbot.api import logger
from ...core.constants import REQUEST_TIMEOUT_SECONDS

# 超时配置
TIMEOUT_CONFIG = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)


@register_engine
class So360ScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取360搜索页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "so360_scrape"

    @property
    def description(self) -> str:
        return "通过抓取360搜索页面提供结果，中文搜索效果好。"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        search_url = f"https://www.so.com/s?q={quote_plus(search_query.query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.so.com/",
        }
        logger.info(
            f"[{self.name}] 正在抓取URL: {search_url} (Timeout={REQUEST_TIMEOUT_SECONDS}s)"
        )
        results_list = []

        async with aiohttp.ClientSession(
            headers=headers, timeout=TIMEOUT_CONFIG
        ) as session:
            try:
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # 360搜索结果解析
                    found_results = False

                    # 360搜索结果的可能选择器
                    selectors_to_try = [
                        # 新版360结构
                        (".res-list .res-item", "h3 a", ".res-desc"),
                        (".res-list .res-item", ".res-title a", ".res-desc"),
                        # 标准360结构
                        (".result", "h3 a", ".res-desc"),
                        (".result", "h3 a", ".res-rich"),
                        # 备用结构
                        (".res-list .result", "h3 a", ".res-desc"),
                        (".res-list .result", ".res-title a", ".res-desc"),
                        # 最新结构
                        (".g", "h3 a", ".s"),
                        (".g", ".r a", ".s"),
                        # 更通用的结构
                        ("li[class*='result']", "a[href]", ""),
                        ("div[class*='result']", "a[href]", ""),
                        ("div[class*='res']", "a[href]", ""),
                    ]

                    for (
                        container_selector,
                        title_selector,
                        snippet_selector,
                    ) in selectors_to_try:
                        if found_results:
                            break

                        containers = soup.select(container_selector)
                        logger.debug(
                            f"[{self.name}] 尝试选择器 '{container_selector}', 找到 {len(containers)} 个容器"
                        )

                        for container in containers:
                            if len(results_list) >= search_query.count:
                                break

                            # 查找标题链接
                            title_tag = container.select_one(title_selector)
                            if not title_tag:
                                continue

                            title_text = title_tag.get_text(strip=True)
                            link_url = title_tag.get("href")

                            if not title_text or not link_url:
                                continue

                            # 过滤掉360自身的链接
                            if "so.com" in link_url or "360.com" in link_url:
                                continue

                            # 处理相对URL
                            if link_url.startswith("/"):
                                link_url = "https://www.so.com" + link_url

                            # 查找描述
                            snippet_text = "无描述"
                            if snippet_selector:
                                snippet_elem = container.select_one(snippet_selector)
                                if snippet_elem:
                                    snippet_text = snippet_elem.get_text(strip=True)

                            if snippet_text == "无描述":
                                # 备用方案：获取容器内所有文本
                                all_text = container.get_text(strip=True)
                                snippet_text = all_text.replace(title_text, "").strip()
                                if len(snippet_text) > 200:
                                    snippet_text = snippet_text[:200] + "..."
                                if not snippet_text or len(snippet_text) < 10:
                                    snippet_text = "无描述"

                            try:
                                result_item = SearchResultItem(
                                    title=title_text,
                                    link=link_url,
                                    snippet=snippet_text,
                                )
                                results_list.append(result_item)
                                found_results = True
                                logger.debug(
                                    f"[{self.name}] 成功解析结果: {title_text}"
                                )
                            except ValidationError as e:
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {link_url}, 错误: {e}"
                                )

                    if not found_results:
                        logger.warning(
                            f"[{self.name}] 未找到任何搜索结果，可能页面结构已变化"
                        )
                        logger.debug(f"[{self.name}] 页面HTML前1000字符: {html[:1000]}")

            except asyncio.TimeoutError:
                logger.error(
                    f"[{self.name}] 抓取超时 ({REQUEST_TIMEOUT_SECONDS}s): {search_url}"
                )
            except ClientResponseError as e:
                logger.error(
                    f"[{self.name}] 抓取时发生 HTTP 错误: 状态码={e.status}, 信息={e.message}, URL={search_url}"
                )
            except ClientError as e:
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
