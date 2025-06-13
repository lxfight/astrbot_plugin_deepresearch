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
class BaiduScrapeSearch(BaseSearchEngine):
    """通过模拟浏览器请求并抓取百度搜索页面来进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "baidu_scrape"

    @property
    def description(self) -> str:
        return "通过抓取百度搜索页面提供结果，无需API密钥，中文搜索效果好。"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def check_config(self) -> bool:
        logger.debug(f"[{self.name}] 配置检查通过（无需特殊配置）。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        search_url = f"https://www.baidu.com/s?wd={quote_plus(search_query.query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
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

                    # 百度搜索结果解析
                    # 百度的搜索结果通常在 class="result" 的 div 中
                    result_divs = soup.find_all("div", class_="result")
                    
                    for result_div in result_divs:
                        # 检查是否已达到所需数量
                        if len(results_list) >= search_query.count:
                            break
                            
                        # 查找标题链接 (通常在 h3 > a 标签中)
                        title_link = result_div.find("h3")
                        if title_link:
                            title_a = title_link.find("a")
                            if not title_a:
                                continue
                        else:
                            # 备用方案：直接查找带href的a标签
                            title_a = result_div.find("a", href=True)
                            if not title_a:
                                continue
                        
                        # 获取URL和标题
                        raw_link = title_a.get("href")
                        title_text = title_a.get_text(strip=True)
                        
                        if not raw_link or not title_text:
                            continue
                        
                        # 百度的链接可能是重定向链接，直接使用
                        link_url = raw_link
                        
                        # 查找描述 (通常在同一div中的后续元素)
                        snippet_text = ""
                        
                        # 方法1: 查找 class 包含 "c-abstract" 的元素
                        abstract_elem = result_div.find(class_=lambda x: x and "c-abstract" in x)
                        if abstract_elem:
                            snippet_text = abstract_elem.get_text(strip=True)
                        
                        # 方法2: 如果没找到，查找包含文本内容的div
                        if not snippet_text:
                            content_divs = result_div.find_all("div")
                            for div in content_divs:
                                div_text = div.get_text(strip=True)
                                # 跳过太短或只包含链接的div
                                if len(div_text) > 20 and not div.find("a"):
                                    snippet_text = div_text
                                    break
                        
                        # 如果仍然没有描述，使用默认值
                        if not snippet_text:
                            snippet_text = "无描述"
                        
                        # 限制描述长度
                        if len(snippet_text) > 200:
                            snippet_text = snippet_text[:200] + "..."

                        try:
                            result_item = SearchResultItem(
                                title=title_text,
                                link=link_url,
                                snippet=snippet_text,
                            )
                            results_list.append(result_item)
                            logger.debug(f"[{self.name}] 成功解析结果: {title_text}")
                        except ValidationError as e:
                            logger.warning(
                                f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {link_url}, 错误: {e}"
                            )

                    if not results_list:
                        # 如果没有找到结果，记录HTML结构用于调试
                        logger.warning(f"[{self.name}] 未找到任何搜索结果，可能页面结构已变化")
                        logger.debug(f"[{self.name}] 页面HTML前500字符: {html[:500]}")

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
