# url_resolver/manager.py
"""URL解析器管理器"""

from typing import List, Optional, Dict, Any
import httpx
from astrbot.api import logger

from .base import BaseURLResolver
from .resolvers import (
    BaiduRedirectResolver,
    BingRedirectResolver,
    GoogleRedirectResolver,
    ShortURLResolver,
    GenericRedirectResolver,
)


class URLResolverManager:
    """URL解析器管理器"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.resolvers: List[BaseURLResolver] = []
        self._initialize_resolvers()

    def _initialize_resolvers(self):
        """初始化所有解析器"""
        resolver_classes = [
            BaiduRedirectResolver,
            BingRedirectResolver,
            GoogleRedirectResolver,
            ShortURLResolver,
            # GenericRedirectResolver 放最后作为备选
        ]

        for resolver_class in resolver_classes:
            try:
                resolver_name = resolver_class.__name__.replace("Resolver", "").lower()
                resolver_config = self.config.get(resolver_name, {})
                resolver = resolver_class(resolver_config)
                self.resolvers.append(resolver)
                logger.debug(f"[URLResolver] 初始化解析器: {resolver.name}")
            except Exception as e:
                logger.warning(
                    f"[URLResolver] 初始化解析器失败 {resolver_class.__name__}: {e}"
                )

        # 最后添加通用解析器
        try:
            generic_config = self.config.get("generic_redirect", {})
            generic_resolver = GenericRedirectResolver(generic_config)
            self.resolvers.append(generic_resolver)
            logger.debug(f"[URLResolver] 初始化通用解析器: {generic_resolver.name}")
        except Exception as e:
            logger.warning(f"[URLResolver] 初始化通用解析器失败: {e}")

    async def resolve_url(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """解析URL，返回真实URL或原URL"""
        if not url:
            return None

        # 遍历所有解析器，找到第一个匹配的
        for resolver in self.resolvers:
            if resolver.can_resolve(url):
                logger.debug(f"[URLResolver] 使用解析器 {resolver.name} 处理: {url}")
                try:
                    resolved_url = await resolver.resolve(url, client)
                    if resolved_url and resolved_url != url:
                        logger.info(
                            f"[URLResolver] URL解析成功: {url} -> {resolved_url}"
                        )
                        return resolved_url
                except Exception as e:
                    logger.warning(
                        f"[URLResolver] 解析器 {resolver.name} 处理失败: {e}"
                    )
                    continue

        # 如果没有解析器能处理，返回原URL
        logger.debug(f"[URLResolver] 无需解析: {url}")
        return url

    def get_resolver_info(self) -> List[Dict[str, Any]]:
        """获取所有解析器的信息"""
        return [
            {
                "name": resolver.name,
                "description": resolver.description,
                "pattern": resolver.pattern,
                "enabled": resolver.enabled,
            }
            for resolver in self.resolvers
        ]

    def enable_resolver(self, name: str):
        """启用指定解析器"""
        for resolver in self.resolvers:
            if resolver.name == name:
                resolver.enabled = True
                logger.info(f"[URLResolver] 启用解析器: {name}")
                return True
        return False

    def disable_resolver(self, name: str):
        """禁用指定解析器"""
        for resolver in self.resolvers:
            if resolver.name == name:
                resolver.enabled = False
                logger.info(f"[URLResolver] 禁用解析器: {name}")
                return True
        return False
