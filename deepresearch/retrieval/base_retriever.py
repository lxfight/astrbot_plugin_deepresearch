from abc import ABC, abstractmethod
from typing import List, Dict, Any

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.base_module import BaseModule
from deepresearch.data_models import RetrievedItem

class BaseRetriever(BaseModule, ABC):
    """
    所有信息检索器的抽象基类。
    定义了检索信息的通用接口。
    """
    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.debug(f"BaseRetriever {self.__class__.__name__} 初始化。")

    @abstractmethod
    async def search(self, query: str, api_config: Dict[str, Any]) -> List[RetrievedItem]:
        """
        根据查询词从信息源中检索信息。
        :param query: 搜索查询词。
        :param api_config: 包含API密钥等配置信息的字典。
        :return: 检索到的信息条目列表。
        """
        pass
