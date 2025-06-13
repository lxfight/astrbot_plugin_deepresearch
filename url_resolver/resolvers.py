# url_resolver/resolvers.py
"""具体的URL解析器实现"""

import re
from urllib.parse import unquote, parse_qs, urlparse
from typing import Optional
import httpx
from astrbot.api import logger

from .base import BaseURLResolver

class BaiduRedirectResolver(BaseURLResolver):
    """百度重定向链接解析器"""
    
    @property
    def name(self) -> str:
        return "baidu_redirect"
    
    @property
    def description(self) -> str:
        return "百度重定向链接解析器"
    
    @property
    def pattern(self) -> str:
        return r"baidu\.com/link"
    
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析百度重定向链接"""
        # 方法1: 尝试通过URL参数解析
        real_url = self._parse_from_url(url)
        if real_url:
            return real_url
        
        # 方法2: 通过HTTP重定向跟踪
        real_url = await self._follow_redirects(url, client)
        if real_url:
            return real_url
        
        # 方法3: 通过响应内容解析
        return await self._extract_from_response(url, client)
    
    def _parse_from_url(self, url: str) -> Optional[str]:
        """从URL参数中直接解析"""
        try:
            # 某些百度链接包含直接的URL参数
            parsed = urlparse(url)
            if parsed.query:
                params = parse_qs(parsed.query)
                # 检查常见的URL参数名
                for param_name in ['url', 'u', 'target', 'link']:
                    if param_name in params:
                        return unquote(params[param_name][0])
        except Exception as e:
            logger.debug(f"[{self.name}] URL参数解析失败: {e}")
        return None

class BingRedirectResolver(BaseURLResolver):
    """Bing重定向链接解析器"""
    
    @property
    def name(self) -> str:
        return "bing_redirect"
    
    @property
    def description(self) -> str:
        return "Bing重定向链接解析器"
    
    @property
    def pattern(self) -> str:
        return r"bing\.com/.*url="
    
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析Bing重定向链接"""
        # 方法1: 从URL中提取
        real_url = self._extract_from_bing_url(url)
        if real_url:
            return real_url
        
        # 方法2: HTTP重定向
        return await self._follow_redirects(url, client)
    
    def _extract_from_bing_url(self, url: str) -> Optional[str]:
        """从Bing URL中提取真实链接"""
        try:
            # Bing链接格式: https://www.bing.com/ck/a?!&&p=...&u=a1aHR0cHM6Ly...
            match = re.search(r'[&?]u=([^&]+)', url)
            if match:
                encoded_url = match.group(1)
                # Bing使用base64编码
                import base64
                try:
                    decoded = base64.b64decode(encoded_url + '===').decode('utf-8')
                    return decoded
                except:
                    # 如果不是base64，可能是URL编码
                    return unquote(encoded_url)
        except Exception as e:
            logger.debug(f"[{self.name}] Bing URL解析失败: {e}")
        return None

class GoogleRedirectResolver(BaseURLResolver):
    """Google重定向链接解析器"""
    
    @property
    def name(self) -> str:
        return "google_redirect"
    
    @property
    def description(self) -> str:
        return "Google重定向链接解析器"
    
    @property
    def pattern(self) -> str:
        return r"google\.com/url"
    
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析Google重定向链接"""
        # Google链接格式: https://www.google.com/url?q=https://example.com&sa=...
        real_url = self._extract_from_google_url(url)
        if real_url:
            return real_url
        
        return await self._follow_redirects(url, client)
    
    def _extract_from_google_url(self, url: str) -> Optional[str]:
        """从Google URL中提取真实链接"""
        try:
            parsed = urlparse(url)
            if parsed.query:
                params = parse_qs(parsed.query)
                if 'q' in params:
                    return unquote(params['q'][0])
        except Exception as e:
            logger.debug(f"[{self.name}] Google URL解析失败: {e}")
        return None

class ShortURLResolver(BaseURLResolver):
    """短链接解析器"""
    
    @property
    def name(self) -> str:
        return "short_url"
    
    @property
    def description(self) -> str:
        return "短链接解析器"
    
    @property
    def pattern(self) -> str:
        return r"(bit\.ly|tinyurl\.com|t\.co|short\.link|dwz\.cn|sina\.lt)"
    
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析短链接"""
        return await self._follow_redirects(url, client)

class GenericRedirectResolver(BaseURLResolver):
    """通用重定向解析器"""
    
    @property
    def name(self) -> str:
        return "generic_redirect"
    
    @property
    def description(self) -> str:
        return "通用重定向解析器"
    
    @property
    def pattern(self) -> str:
        return r".*"  # 匹配所有URL，作为最后的备选
    
    def can_resolve(self, url: str) -> bool:
        """只有在其他解析器都不能处理时才使用"""
        return self.enabled
    
    async def resolve(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """通用重定向解析"""
        try:
            response = await client.head(url, follow_redirects=True, timeout=self.timeout)
            final_url = str(response.url)
            
            if final_url != url:
                logger.info(f"[{self.name}] 通用重定向解析: {url} -> {final_url}")
                return final_url
        except Exception as e:
            logger.debug(f"[{self.name}] 通用重定向解析失败: {url}, 错误: {e}")
        
        return None
