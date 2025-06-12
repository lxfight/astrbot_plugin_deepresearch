import time
import asyncio  # <-- 新增
from typing import Dict, Any
import json  # <-- 新增: 捕获 JSON 解码错误

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout  # <-- 新增
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
class GoogleApiSearch(BaseSearchEngine):
    """使用 Google Custom Search JSON API 进行搜索的引擎。"""

    @property
    def name(self) -> str:
        return "google_api"

    @property
    def description(self) -> str:
        return "通过 Google Custom Search API 提供搜索结果，稳定可靠。"

    # __init__ 和 check_config 基本保持不变
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        engine_config = self.config.get(self.name, {})
        self.api_key = engine_config.get("api_key")
        self.cse_id = engine_config.get("cse_id")
        self.api_url = "https://www.googleapis.com/customsearch/v1"
        logger.debug(
            f"[{self.name}] 初始化完成。 API_KEY={'*' * 6 if self.api_key else 'None'}, CSE_ID={self.cse_id or 'None'}"
        )  # 隐藏key

    async def check_config(self) -> bool:
        # 检查逻辑保持不变
        if not self.api_key or not self.cse_id:
            logger.warning(f"[{self.name}] 注册失败：缺少 'api_key' 或 'cse_id'。")
            return False
        logger.debug(f"[{self.name}] 配置检查通过。")
        return True

    async def search(self, search_query: SearchQuery) -> SearchResponse:
        start_time = time.time()
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": search_query.query,
            "num": search_query.count,
        }
        # 检查配置，防止用无效的 key/id 发起请求
        if not self.api_key or not self.cse_id:
            logger.error(f"[{self.name}] 配置不完整，拒绝执行搜索。")
            return SearchResponse(
                query=search_query,
                engine_name=self.name,
                results=[],
                search_time_seconds=0,
            )

        logger.info(
            f"[{self.name}] 正在搜索: '{search_query.query}' (Timeout={REQUEST_TIMEOUT_SECONDS}s)"
        )
        results_list = []
        estimated_total = None

        # --- 修改: session 中加入 timeout ---
        async with aiohttp.ClientSession(timeout=TIMEOUT_CONFIG) as session:
            try:
                async with session.get(self.api_url, params=params) as response:
                    # 检查状态码，对于API，非200都应视为错误
                    response.raise_for_status()
                    # 增加 JSON 解码错误捕获
                    try:
                        data = await response.json()
                    except json.JSONDecodeError:
                        text = await response.text()
                        logger.error(
                            f"[{self.name}] API 返回了非 JSON 内容: {text[:200]}..."
                        )
                        data = {}  # 避免后续引用 data 出错

                    if "error" in data:
                        error_msg = data.get("error", {}).get("message", "未知API错误")
                        status_code = data.get("error", {}).get("code", "N/A")
                        logger.error(
                            f"[{self.name}] Google API 返回错误 (Code {status_code}): {error_msg}"
                        )
                        # 如果是配额用尽等错误, 应该直接返回, 不再继续处理
                        # return ...

                    # --- 修改: 增加 int 转换的异常捕获 ---
                    try:
                        if (
                            "searchInformation" in data
                            and "totalResults" in data["searchInformation"]
                        ):
                            # totalResults 是字符串 "123000"
                            total_str = data["searchInformation"]["totalResults"]
                            estimated_total = int(total_str) if total_str else 0
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            f"[{self.name}] 无法解析 'totalResults': {data.get('searchInformation', {}).get('totalResults')}, 错误: {e}"
                        )
                        estimated_total = None  # 确保是 None
                    # ------------------------------------

                    for item in data.get("items", []):
                        # 达到所需数量时可以提前停止 (API num参数已限制，此处非必需但可作为防御)
                        if len(results_list) >= search_query.count:
                            break
                        try:
                            result_item = SearchResultItem(
                                title=item.get("title", "无标题"),
                                link=item.get("link", ""),
                                snippet=item.get("snippet", "无摘要"),
                            )
                            results_list.append(result_item)
                        except ValidationError as e:
                            logger.warning(
                                f"[{self.name}] 过滤掉一条来自API的无效结果。Link: {item.get('link')}, 错误: {e}"
                            )

            # --- 新增: 捕获超时和 HTTP 错误 ---
            except asyncio.TimeoutError:
                logger.error(
                    f"[{self.name}] API 请求超时 ({REQUEST_TIMEOUT_SECONDS}s): {self.api_url}"
                )
            except ClientResponseError as e:
                # e.g., 403 (key invalid/quota), 400 (bad request)
                logger.error(
                    f"[{self.name}] API 请求发生 HTTP 错误: 状态码={e.status}, 信息={e.message}"
                )
            # --------------------------------
            except ClientError as e:  # ClientError
                logger.error(f"[{self.name}] 请求API时发生网络错误: {e}")
            except Exception as e:
                logger.error(
                    f"[{self.name}] 处理API响应时发生未知错误: {e}", exc_info=True
                )

        end_time = time.time()
        return SearchResponse(
            query=search_query,
            engine_name=self.name,
            results=results_list,
            search_time_seconds=round(end_time - start_time, 4),
            estimated_total_results=estimated_total,
        )
