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
        # 修改为使用DuckDuckGo的Lite版本，更稳定
        search_url = f"https://duckduckgo.com/lite/?q={quote_plus(search_query.query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        logger.info(
            f"[{self.name}] 正在抓取URL: {search_url} (Timeout={REQUEST_TIMEOUT_SECONDS}s)"
        )
        results_list = []

        # 创建更宽松的SSL配置
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100, limit_per_host=30)
        
        # --- 修改: session 中加入 timeout 和 connector ---
        async with aiohttp.ClientSession(
            headers=headers, timeout=TIMEOUT_CONFIG, connector=connector
        ) as session:
            try:
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    html = await response.text()
                    soup = BeautifulSoup(html, "html.parser")

                    # DuckDuckGo Lite版本的结果解析
                    # 查找搜索结果表格
                    results_table = soup.find("table", {"bgcolor": "white"})
                    if results_table:
                        # 在表格中查找所有链接行
                        result_rows = results_table.find_all("tr")
                        for row in result_rows:
                            # --- 检查是否已达到所需数量 ---
                            if len(results_list) >= search_query.count:
                                break
                            
                            # 查找标题链接
                            title_link = row.find("a", href=True)
                            if not title_link:
                                continue
                                
                            # 获取URL
                            raw_link = title_link.get("href")
                            if not raw_link or raw_link.startswith("/"):
                                continue  # 跳过相对链接或空链接
                            
                            # 获取标题
                            title_text = title_link.get_text(strip=True)
                            if not title_text:
                                continue
                            
                            # 查找描述文本（通常在下一行或同一单元格）
                            snippet_text = ""
                            next_sibling = title_link.find_next_sibling(string=True)
                            if next_sibling:
                                snippet_text = next_sibling.strip()
                            
                            # 如果没有找到同级描述，查找父级容器中的文本
                            if not snippet_text:
                                parent_cell = title_link.find_parent("td")
                                if parent_cell:
                                    all_text = parent_cell.get_text(strip=True)
                                    # 移除标题部分，剩下的作为描述
                                    snippet_text = all_text.replace(title_text, "").strip()
                            
                            # 如果仍然没有描述，使用默认值
                            if not snippet_text:
                                snippet_text = "无描述"

                            try:
                                result_item = SearchResultItem(
                                    title=title_text,
                                    link=raw_link,
                                    snippet=snippet_text,
                                )
                                results_list.append(result_item)
                                logger.debug(f"[{self.name}] 成功解析结果: {title_text}")
                            except ValidationError as e:
                                logger.warning(
                                    f"[{self.name}] 过滤掉一条解析出的无效结果。URL: {raw_link}, 错误: {e}"
                                )
                    else:
                        # 如果没有找到结果表格，记录HTML结构用于调试
                        logger.warning(f"[{self.name}] 未找到搜索结果表格，可能页面结构已变化")
                        logger.debug(f"[{self.name}] 页面HTML前500字符: {html[:500]}")

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
