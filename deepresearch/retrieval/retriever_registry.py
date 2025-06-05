from typing import Dict, Type, Callable, Literal

from astrbot.api import logger
from .base_retriever import BaseRetriever


class RetrieverRegistry:
    """
    检索器注册中心，用于收集所有可用的检索器类。
    """

    _retrievers: Dict[
        str, Type[BaseRetriever]
    ] = {}  # 键为检索器类型字符串，值为检索器类

    @classmethod
    def register(
        cls, source_type: Literal["web", "news", "academic", "custom"]
    ) -> Callable[[Type[BaseRetriever]], Type[BaseRetriever]]:
        """
        注册一个检索器类。
        :param source_type: 检索器所属的来源类型 (web, news, academic, custom)。
        """

        def decorator(retriever_cls: Type[BaseRetriever]) -> Type[BaseRetriever]:
            if not issubclass(retriever_cls, BaseRetriever):
                logger.error(
                    f"尝试注册的类 {retriever_cls.__name__} 不是 BaseRetriever 的子类，注册失败。"
                )
                raise TypeError(
                    f"Class {retriever_cls.__name__} must inherit from BaseRetriever."
                )

            # 将 source_type 属性直接添加到类上
            retriever_cls.source_type = source_type  # type: ignore

            if source_type in cls._retrievers:
                logger.warning(
                    f"检索器类型 '{source_type}' 已被注册，将覆盖旧的检索器：{cls._retrievers[source_type].__name__} -> {retriever_cls.__name__}"
                )

            cls._retrievers[source_type] = retriever_cls
            logger.info(f"检索器 '{retriever_cls.__name__}' ({source_type}) 已注册。")
            return retriever_cls

        return decorator

    @classmethod
    def get_retriever_classes(cls) -> Dict[str, Type[BaseRetriever]]:
        """
        获取所有已注册的检索器类。
        """
        return cls._retrievers


# 创建一个别名方便使用
register_retriever = RetrieverRegistry.register
