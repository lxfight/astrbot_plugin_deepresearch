# url_resolver/base.py
"""URL解析器基类"""

import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import httpx
from astrbot.api import logger


class BaseURLResolver(ABC):
    """URL解析器基类"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.timeout = self.config.get("timeout", 10.0)

    @property
    @abstractmethod
    def name(self) -> str:
        """解析器名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """解析器描述"""
        pass

    @property
    @abstractmethod
    def pattern(self) -> str:
        """匹配URL的正则表达式模式"""
        pass

    def can_resolve(self, url: str) -> bool:
        """检查是否可以解析此URL"""
        if not self.enabled:
            return False
        return bool(re.search(self.pattern, url, re.IGNORECASE))

    @abstractmethod
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析URL，返回真实URL或None"""
        pass

    async def _follow_redirects(
        self, url: str, client: httpx.AsyncClient, max_redirects: int = 5
    ) -> Optional[str]:
        """通用重定向跟踪方法"""
        try:
            response = await client.get(
                url, follow_redirects=True, timeout=self.timeout
            )
            final_url = str(response.url)

            # 检查是否成功解析
            if final_url != url and not self.can_resolve(final_url):
                logger.info(f"[{self.name}] 重定向解析成功: {url} -> {final_url}")
                return final_url
            else:
                logger.warning(f"[{self.name}] 重定向解析失败，未能获取真实URL: {url}")
                return None

        except Exception as e:
            logger.warning(f"[{self.name}] 重定向解析异常: {url}, 错误: {e}")
            return None

    async def _extract_from_response(
        self, url: str, client: httpx.AsyncClient
    ) -> Optional[str]:
        """从响应内容中提取真实URL"""
        try:
            response = await client.get(
                url, follow_redirects=False, timeout=self.timeout
            )

            # 检查重定向响应
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if location:
                    # 处理相对URL
                    if location.startswith("/"):
                        from urllib.parse import urljoin

                        location = urljoin(url, location)
                    logger.info(f"[{self.name}] HTTP重定向解析: {url} -> {location}")
                    return location

            # 如果没有重定向，尝试解析HTML中的跳转
            if response.status_code == 200:
                content = response.text
                return self._extract_from_html(content, url)

        except Exception as e:
            logger.warning(f"[{self.name}] 响应解析异常: {url}, 错误: {e}")

        return None

    def _extract_from_html(self, html_content: str, original_url: str) -> Optional[str]:
        """从HTML内容中提取真实URL（可被子类重写）"""
        # 查找meta refresh
        meta_refresh_pattern = r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\'>\s]+)'
        match = re.search(meta_refresh_pattern, html_content, re.IGNORECASE)
        if match:
            return match.group(1)

        # 查找JavaScript跳转
        js_redirect_pattern = r'window\.location\.href\s*=\s*["\']([^"\']+)["\']'
        match = re.search(js_redirect_pattern, html_content, re.IGNORECASE)
        if match:
            return match.group(1)

        return None
