from typing import Dict, Type, Callable, Literal, Optional, List, Any
import inspect
from datetime import datetime

from astrbot.api import logger
from .base_retriever import BaseRetriever


class RetrieverMetadata:
    """检索器元数据类"""

    def __init__(self, retriever_cls: Type[BaseRetriever], source_type: str):
        self.retriever_cls = retriever_cls
        self.source_type = source_type
        self.name = retriever_cls.__name__
        self.module = retriever_cls.__module__
        self.description = self._extract_description(retriever_cls)
        self.registered_at = datetime.now()
        self.config_requirements = self._extract_config_requirements(retriever_cls)

    def _extract_description(self, cls: Type[BaseRetriever]) -> str:
        """提取类的描述信息"""
        if cls.__doc__:
            # 提取第一行作为简短描述
            return cls.__doc__.strip().split("\n")[0]
        return f"{cls.__name__} 检索器"

    def _extract_config_requirements(self, cls: Type[BaseRetriever]) -> List[str]:
        """分析检索器的配置需求"""
        requirements = []

        # 检查 check_config_valid 方法的实现来推断配置需求
        try:
            source_code = inspect.getsource(cls.check_config_valid)

            # 简单的模式匹配来找到配置键
            import re

            patterns = [
                r'api_config\.get\(["\']([^"\']+)["\']',
                r'config\.get\(["\']([^"\']+)["\']',
            ]

            for pattern in patterns:
                matches = re.findall(pattern, source_code)
                requirements.extend(matches)

        except Exception as e:
            logger.debug(f"无法分析 {cls.__name__} 的配置需求: {e}")

        return list(set(requirements))  # 去重

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "source_type": self.source_type,
            "module": self.module,
            "description": self.description,
            "registered_at": self.registered_at.isoformat(),
            "config_requirements": self.config_requirements,
        }


class RetrieverRegistry:
    """
    检索器注册中心，用于收集所有可用的检索器类。
    提供检索器的注册、查询、验证等功能。
    """

    _retrievers: Dict[str, RetrieverMetadata] = {}  # 键为检索器类型字符串，值为元数据
    _aliases: Dict[str, str] = {}  # 别名映射
    _initialization_order: List[str] = []  # 初始化顺序
    _registry_locked: bool = False  # 注册表锁定状态

    @classmethod
    def register(
        cls,
        source_type: Literal["web", "news", "academic", "custom"],
        alias: Optional[str] = None,
        priority: int = 0,
    ) -> Callable[[Type[BaseRetriever]], Type[BaseRetriever]]:
        """
        注册一个检索器类。

        Args:
            source_type: 检索器所属的来源类型
            alias: 检索器别名
            priority: 初始化优先级（数字越大优先级越高）
        """

        def decorator(retriever_cls: Type[BaseRetriever]) -> Type[BaseRetriever]:
            if cls._registry_locked:
                logger.warning(f"注册表已锁定，无法注册 {retriever_cls.__name__}")
                return retriever_cls

            # 验证类型
            if not cls._validate_retriever_class(retriever_cls):
                return retriever_cls

            # 将 source_type 属性直接添加到类上
            retriever_cls.source_type = source_type  # type: ignore
            retriever_cls._registry_priority = priority  # type: ignore

            # 检查是否已注册
            if source_type in cls._retrievers:
                existing_metadata = cls._retrievers[source_type]
                logger.warning(
                    f"检索器类型 '{source_type}' 已被注册，将覆盖旧的检索器：{existing_metadata.name} -> {retriever_cls.__name__}"
                )

            # 创建元数据并注册
            metadata = RetrieverMetadata(retriever_cls, source_type)
            cls._retrievers[source_type] = metadata

            # 处理别名
            if alias:
                cls._aliases[alias] = source_type

            # 更新初始化顺序
            cls._update_initialization_order(source_type, priority)

            logger.info(f"检索器 '{retriever_cls.__name__}' ({source_type}) 已注册")
            return retriever_cls

        return decorator

    @classmethod
    def _validate_retriever_class(cls, retriever_cls: Type[BaseRetriever]) -> bool:
        """验证检索器类的有效性"""
        if not inspect.isclass(retriever_cls):
            logger.error(f"{retriever_cls} 不是一个类")
            return False

        if not issubclass(retriever_cls, BaseRetriever):
            logger.error(
                f"尝试注册的类 {retriever_cls.__name__} 不是 BaseRetriever 的子类，注册失败"
            )
            return False

        # 检查必需方法是否已实现
        required_methods = ["check_config_valid", "search"]
        for method_name in required_methods:
            if not hasattr(retriever_cls, method_name):
                logger.error(f"{retriever_cls.__name__} 缺少必需方法: {method_name}")
                return False

            method = getattr(retriever_cls, method_name)
            if not callable(method):
                logger.error(f"{retriever_cls.__name__}.{method_name} 不是可调用方法")
                return False

        return True

    @classmethod
    def _update_initialization_order(cls, source_type: str, priority: int):
        """更新初始化顺序"""
        # 移除已存在的类型
        if source_type in cls._initialization_order:
            cls._initialization_order.remove(source_type)

        # 按优先级插入
        inserted = False
        for i, existing_type in enumerate(cls._initialization_order):
            existing_priority = getattr(
                cls._retrievers[existing_type].retriever_cls, "_registry_priority", 0
            )
            if priority > existing_priority:
                cls._initialization_order.insert(i, source_type)
                inserted = True
                break

        if not inserted:
            cls._initialization_order.append(source_type)

    @classmethod
    def get_retriever_classes(cls) -> Dict[str, Type[BaseRetriever]]:
        """获取所有已注册的检索器类"""
        return {
            source_type: metadata.retriever_cls
            for source_type, metadata in cls._retrievers.items()
        }

    @classmethod
    def get_retriever_class(cls, source_type: str) -> Optional[Type[BaseRetriever]]:
        """获取指定类型的检索器类"""
        # 检查别名
        actual_type = cls._aliases.get(source_type, source_type)

        metadata = cls._retrievers.get(actual_type)
        return metadata.retriever_cls if metadata else None

    @classmethod
    def get_retriever_metadata(cls, source_type: str) -> Optional[RetrieverMetadata]:
        """获取指定类型的检索器元数据"""
        actual_type = cls._aliases.get(source_type, source_type)
        return cls._retrievers.get(actual_type)

    @classmethod
    def list_available_types(cls) -> List[str]:
        """列出所有可用的检索器类型"""
        return list(cls._retrievers.keys())

    @classmethod
    def list_aliases(cls) -> Dict[str, str]:
        """列出所有别名映射"""
        return cls._aliases.copy()

    @classmethod
    def get_initialization_order(cls) -> List[str]:
        """获取初始化顺序"""
        return cls._initialization_order.copy()

    @classmethod
    def get_registry_info(cls) -> Dict[str, Any]:
        """获取注册表完整信息"""
        return {
            "total_retrievers": len(cls._retrievers),
            "retrievers": {
                source_type: metadata.to_dict()
                for source_type, metadata in cls._retrievers.items()
            },
            "aliases": cls._aliases.copy(),
            "initialization_order": cls._initialization_order.copy(),
            "locked": cls._registry_locked,
        }

    @classmethod
    def validate_retriever_config(
        cls, source_type: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """验证指定检索器的配置"""
        metadata = cls.get_retriever_metadata(source_type)
        if not metadata:
            return {"valid": False, "error": f"未找到类型为 '{source_type}' 的检索器"}

        try:
            # 创建临时实例进行配置验证
            from astrbot.api import AstrBotConfig

            # 这里需要模拟context，实际使用中应该传入真实的context
            temp_context = None  # 在实际使用中需要传入有效的context
            temp_config = AstrBotConfig(config)

            temp_instance = metadata.retriever_cls(temp_context, temp_config)
            is_valid = temp_instance.check_config_valid(config)

            return {
                "valid": is_valid,
                "requirements": metadata.config_requirements,
                "missing_configs": [
                    req
                    for req in metadata.config_requirements
                    if req not in config or not config[req]
                ]
                if not is_valid
                else [],
            }

        except Exception as e:
            return {"valid": False, "error": f"配置验证失败: {str(e)}"}

    @classmethod
    def lock_registry(cls):
        """锁定注册表，防止进一步注册"""
        cls._registry_locked = True
        logger.info("检索器注册表已锁定")

    @classmethod
    def unlock_registry(cls):
        """解锁注册表"""
        cls._registry_locked = False
        logger.info("检索器注册表已解锁")

    @classmethod
    def clear_registry(cls):
        """清空注册表（仅用于测试）"""
        if cls._registry_locked:
            logger.warning("注册表已锁定，无法清空")
            return

        cls._retrievers.clear()
        cls._aliases.clear()
        cls._initialization_order.clear()
        logger.info("检索器注册表已清空")

    @classmethod
    def unregister(cls, source_type: str) -> bool:
        """注销指定类型的检索器"""
        if cls._registry_locked:
            logger.warning(f"注册表已锁定，无法注销 {source_type}")
            return False

        if source_type not in cls._retrievers:
            logger.warning(f"未找到类型为 '{source_type}' 的检索器")
            return False

        # 移除检索器
        del cls._retrievers[source_type]

        # 移除相关别名
        aliases_to_remove = [
            alias for alias, target in cls._aliases.items() if target == source_type
        ]
        for alias in aliases_to_remove:
            del cls._aliases[alias]

        # 从初始化顺序中移除
        if source_type in cls._initialization_order:
            cls._initialization_order.remove(source_type)

        logger.info(f"检索器 '{source_type}' 已注销")
        return True

    @classmethod
    def get_priority(cls, source_type: str) -> int:
        """获取检索器的优先级"""
        metadata = cls._retrievers.get(source_type)
        if metadata and hasattr(metadata.retriever_cls, "_registry_priority"):
            return getattr(metadata.retriever_cls, "_registry_priority", 0)
        return 0


# 创建便捷的注册装饰器
def register_retriever(
    source_type: Literal["web", "news", "academic", "custom"],
    alias: Optional[str] = None,
    priority: int = 0,
):
    """便捷的检索器注册装饰器"""
    return RetrieverRegistry.register(source_type, alias, priority)


# 创建便捷的查询函数
def get_retriever_class(source_type: str) -> Optional[Type[BaseRetriever]]:
    """获取检索器类的便捷函数"""
    return RetrieverRegistry.get_retriever_class(source_type)


def list_available_retrievers() -> List[str]:
    """列出可用检索器的便捷函数"""
    return RetrieverRegistry.list_available_types()
