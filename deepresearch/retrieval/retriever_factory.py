from typing import Dict, Optional, Literal

from astrbot.api import star, AstrBotConfig
from deepresearch.base_module import BaseModule
from deepresearch.retrieval.base_retriever import BaseRetriever
from deepresearch.retrieval.retriever_registry import RetrieverRegistry


class RetrieverFactory(BaseModule):
    """
    检索器工厂，根据配置动态创建和提供可用的检索器实例。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self._available_retrievers: Dict[str, BaseRetriever] = {}
        self.initialize_retrievers()
        self.logger.info("RetrieverFactory 模块初始化完成。")

    def initialize_retrievers(self):
        """
        初始化所有已注册且配置有效的检索器。
        """
        api_config = self.config.get("search_config", {})
        for (
            source_type,
            retriever_cls,
        ) in RetrieverRegistry.get_retriever_classes().items():
            try:
                # 实例化检索器
                retriever_instance = retriever_cls(self.context, self.config)
                # 检查配置是否有效
                if retriever_instance.check_config_valid(api_config):
                    self._available_retrievers[source_type] = retriever_instance
                    self.logger.info(
                        f"检索器 '{retriever_cls.__name__}' ({source_type}) 配置有效并已载入。"
                    )
                else:
                    self.logger.warning(
                        f"检索器 '{retriever_cls.__name__}' ({source_type}) 配置无效，将跳过载入。"
                    )
            except Exception as e:
                self.logger.error(
                    f"初始化检索器 '{retriever_cls.__name__}' ({source_type}) 失败: {e}",
                    exc_info=True,
                )

    def get_available_retrievers(self) -> Dict[str, BaseRetriever]:
        """
        获取当前已实例化且配置有效的检索器字典。
        键为 source_type，值为检索器实例。
        """
        return self._available_retrievers

    def get_retriever(
        self, source_type: Literal["web", "news", "academic", "custom"]
    ) -> Optional[BaseRetriever]:
        """
        根据来源类型获取特定的检索器实例。
        """
        return self._available_retrievers.get(source_type)
