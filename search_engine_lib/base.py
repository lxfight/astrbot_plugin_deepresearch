# coding: utf-8
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from astrbot.api import logger
from .models import SearchQuery, SearchResponse


class BaseSearchEngine(ABC):
    """
    搜索引擎的抽象基类 (Abstract Base Class)。
    所有具体的搜索引擎实现都必须继承此类，并实现其所有抽象方法和属性。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化基类。
        :param config: 一个字典，包含该搜索引擎可能需要的配置项，如 API Key。
        """
        self.config = config or {}
        logger.debug(f"正在初始化搜索引擎: {self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        """
        返回搜索引擎的唯一标识名称（全小写，下划线分隔）。
        例如: 'google_api', 'duckduckgo_scrape'
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """
        返回对该搜索引擎的简短描述。
        """
        raise NotImplementedError

    @abstractmethod
    async def check_config(self) -> bool:
        """
        异步检查当前配置是否足以让该搜索引擎正常工作。
        例如，检查必要的 API 密钥是否存在。

        :return: 如果配置完整且有效，返回 True；否则返回 False。
        """
        raise NotImplementedError

    @abstractmethod
    async def search(self, search_query: SearchQuery) -> SearchResponse:
        """
        执行异步搜索。

        :param search_query: 一个包含查询详情的 SearchQuery 对象。
        :return: 一个包含搜索结果和元数据的 SearchResponse 对象。
        """
        raise NotImplementedError
