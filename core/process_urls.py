import asyncio
from typing import List, Optional
import aiohttp
import trafilatura
from pydantic import BaseModel, Field

from ..search_engine_lib.models import SearchResultItem


class ProcessedResult(BaseModel):
    """
    一个经过处理和内容提取后的结果模型。
    """

    source: SearchResultItem = Field(
        ..., description="原始的、未经处理的搜索结果条目。"
    )
    main_content: Optional[str] = Field(
        None, description="从原始链接中智能提取出的主要文本内容。如果提取失败则为None。"
    )
    extraction_status: str = Field(
        ..., description="内容提取的状态 (例如: 'success', 'failed: network error')"
    )


class AsyncUrlTextExtractor:
    """
    用于高并发的URL内容提取。
    """

    def __init__(self, session: aiohttp.ClientSession, url: str, timeout: int = 10):
        self.session = session
        self.url = url
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self._error_message: Optional[str] = None

    async def _fetch_html(self) -> Optional[str]:
        """异步获取HTML内容。"""
        try:
            async with self.session.get(
                self.url,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:
            self._error_message = f"network error: {type(e).__name__}"
            return None

    async def extract(self) -> Optional[str]:
        """执行异步提取，返回主要文本内容。"""
        html_content = await self._fetch_html()
        if not html_content:
            return None

        # trafilatura是CPU密集型操作, 使用run_in_executor在线程池中运行以避免阻塞事件循环。
        loop = asyncio.get_running_loop()
        main_text = await loop.run_in_executor(
            None, trafilatura.extract, html_content, False, False
        )

        if not main_text:
            self._error_message = "无提取的内容"
            return None

        return main_text


class SearchResultsProcessor:
    """
    处理搜索引擎返回的结果，并使用提取器丰富它们。
    此版本使用组合模型 ProcessedResult 以降低耦合度，并提供同步和异步方法。
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    async def _process_single_item_async(
        self, session: aiohttp.ClientSession, item: SearchResultItem
    ) -> ProcessedResult:
        """[内部] 异步处理单个项目。"""
        url = str(item.link)
        extractor = AsyncUrlTextExtractor(session, url, self.timeout)
        content = await extractor.extract()

        return ProcessedResult(
            source=item,
            main_content=content,
            extraction_status="success"
            if content
            else f"failed: {getattr(extractor, '_error_message', 'unknown')}",
        )

    async def process_async(
        self, results: List[SearchResultItem]
    ) -> List[ProcessedResult]:
        """
        [异步] 处理搜索结果列表。并发地从所有URL提取内容，性能极高。
        """
        async with aiohttp.ClientSession() as session:
            tasks = [self._process_single_item_async(session, item) for item in results]
            processed_results = await asyncio.gather(*tasks, return_exceptions=True)

            final_results = []
            for i, result in enumerate(processed_results):
                if isinstance(result, Exception):
                    final_results.append(
                        ProcessedResult(
                            source=results[i],
                            main_content=None,
                            extraction_status=f"failed: unexpected error - {result}",
                        )
                    )
                else:
                    final_results.append(result)
            return final_results
