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

                    # 改进的Bing搜索结果解析
                    found_results = False

                    # 方法1: 寻找标准的搜索结果
                    selectors_to_try = [
                        # 新版Bing结构
                        ("ol#b_results li.b_algo", "h2 a", ".b_caption p"),
                        ("ol#b_results li", "h2 a", ".b_caption"),
                        # 旧版结构
                        ("li.b_algo", "h2 a", ".b_caption p"),
                        ("li.b_algo", "h3 a", ".b_caption"),
                        # 更通用的结构
                        (".b_algo", "a[href]", ".b_caption"),
                        # 其他可能的结构
                        (".sr_rslts .g", "h3 a", ".st"),
                        ("div[data-hveid]", "h3 a", ".st"),
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

                            # 查找描述
                            snippet_text = "无描述"
                            snippet_elem = container.select_one(snippet_selector)
                            if snippet_elem:
                                snippet_text = snippet_elem.get_text(strip=True)
                            else:
                                # 备用方案：获取容器内所有文本
                                all_text = container.get_text(strip=True)
                                # 移除标题部分，剩下的作为描述
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
                        # 保存HTML用于调试
                        logger.debug(f"[{self.name}] 页面HTML前1000字符: {html[:1000]}")

                        # 尝试最后的备用方案：查找所有包含href的链接
                        all_links = soup.find_all("a", href=True)
                        valid_links = []
                        for link in all_links:
                            href = link.get("href")
                            text = link.get_text(strip=True)
                            # 过滤掉明显不是搜索结果的链接
                            if (
                                href
                                and text
                                and not href.startswith("#")
                                and not "bing.com" in href
                                and len(text) > 5
                                and len(text) < 200
                            ):
                                valid_links.append((text, href))

                        # 取前几个有效链接
                        for i, (title_text, link_url) in enumerate(
                            valid_links[: search_query.count]
                        ):
                            try:
                                result_item = SearchResultItem(
                                    title=title_text,
                                    link=link_url,
                                    snippet="从页面链接提取的结果",
                                )
                                results_list.append(result_item)
                                found_results = True
                            except ValidationError:
                                continue

                        if found_results:
                            logger.info(
                                f"[{self.name}] 使用备用方案成功提取了 {len(results_list)} 个结果"
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
