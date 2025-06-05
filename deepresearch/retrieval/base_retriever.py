from abc import ABC, abstractmethod
from typing import List, Dict, Any, Literal

from astrbot.api import star, AstrBotConfig
from ..base_module import BaseModule
from ..data_models import RetrievedItem

# from .retriever_registry import register_retriever


class BaseRetriever(BaseModule, ABC):
    """
    所有信息检索器的抽象基类。
    定义了检索信息的通用接口。
    """

    # 抽象属性，必须在子类中定义
    source_type: Literal["web", "news", "academic", "custom"]  # 检索器类型，用于识别

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        # 确保子类定义了 source_type
        if not hasattr(self, "source_type"):
            raise NotImplementedError(
                f"Retriever class {self.__class__.__name__} must define 'source_type' attribute."
            )
        self.logger.debug(
            f"BaseRetriever {self.__class__.__name__} 初始化，类型: {self.source_type}."
        )

    @abstractmethod
    def check_config_valid(self, api_config: Dict[str, Any]) -> bool:
        """
        检查当前检索器是否已正确配置，可以正常工作。
        例如，检查所需的 API Key 是否存在且有效。
        :param api_config: 包含API密钥等配置信息的字典。
        :return: 如果配置有效则返回 True，否则返回 False。
        """
        pass

    @abstractmethod
    async def search(
        self, query: str, api_config: Dict[str, Any]
    ) -> List[RetrievedItem]:
        """
        根据查询词从信息源中检索信息。
        :param query: 搜索查询词。
        :param api_config: 包含API密钥等配置信息的字典。
        :return: 检索到的信息条目列表。
        """
        pass
