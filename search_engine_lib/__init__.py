import asyncio
import inspect
from astrbot.api import logger
from typing import Dict, List, Optional, Type

from .base import BaseSearchEngine


# --- 注册器核心 ---

# _class_registry: 存储被 @register_engine 装饰器标记的 *类*。
# 这是个临时区域，在模块导入时填充。
# 键是引擎名称(str)，值是引擎类(Type[BaseSearchEngine])。
_class_registry: Dict[str, Type[BaseSearchEngine]] = {}

# _engine_registry: 存储最终初始化并验证通过的搜索引擎 *实例*。
# 这是最终提供给外部使用的注册表。
# 键是引擎名称(str)，值是引擎实例(BaseSearchEngine)。
_engine_registry: Dict[str, BaseSearchEngine] = {}


def register_engine(cls: Type[BaseSearchEngine]) -> Type[BaseSearchEngine]:
    """
    一个类装饰器，用于自动注册搜索引擎类。
    """
    # 确保被装饰的是 BaseSearchEngine 的子类
    if not inspect.isclass(cls) or not issubclass(cls, BaseSearchEngine):
        raise TypeError(
            f"被 @register_engine 装饰的对象 {cls.__name__} 不是 BaseSearchEngine 的有效子类。"
        )

    # 为了获取 name，我们需要临时创建一个实例。
    # 这里的 config 是一个空字典，因为此时我们还没有用户的实际配置。
    # 搜索引擎的 __init__ 应该能够处理这种情况。
    try:
        temp_instance = cls(config={})
        name = temp_instance.name
    except Exception as e:
        logger.error(
            f"在尝试注册类 {cls.__name__} 时获取其名称失败: {e}", exc_info=True
        )
        return cls  # 返回原类，但不进行注册

    if name in _class_registry:
        logger.warning(
            f"引擎名称冲突: '{name}' 已被注册。类 {cls.__name__} 将覆盖之前的注册。"
        )

    _class_registry[name] = cls
    logger.debug(f"已发现并暂存引擎类: '{name}' (来自 {cls.__name__})")

    # 装饰器必须返回原类
    return cls


async def initialize(config: Optional[Dict] = None):
    """
    异步初始化搜索引擎库。
    它会处理所有通过 @register_engine 注册的类，
    创建实例，进行异步配置检查，并将成功的实例放入最终的注册表。
    """
    if _engine_registry:
        logger.warning("搜索引擎库已初始化，跳过重复操作。")
        return

    logger.info("开始初始化搜索引擎库...")

    if not _class_registry:
        logger.warning("未发现任何通过 @register_engine 注册的引擎。")
        return

    # 为每个待处理的类创建一个异步验证任务
    initialization_tasks = []
    for name, engine_class in _class_registry.items():
        task = _initialize_and_validate_engine(name, engine_class, config)
        initialization_tasks.append(task)

    # 并发执行所有初始化和验证任务
    await asyncio.gather(*initialization_tasks)

    logger.info(
        f"搜索引擎库初始化完成。成功注册的引擎: {list(_engine_registry.keys())}"
    )


async def _initialize_and_validate_engine(
    name: str, engine_class: Type[BaseSearchEngine], config: Optional[Dict]
):
    """
    (内部函数) 异步处理单个搜索引擎的实例化、验证和最终注册。
    """
    try:
        # 1. 实例化搜索引擎，传入全局配置
        instance = engine_class(config=config)

        # 2. 异步检查配置是否有效
        is_configured = await instance.check_config()

        # 3. 如果配置有效，则加入到最终的可用引擎注册表中
        if is_configured:
            _engine_registry[name] = instance
            logger.info(f"✅ 引擎 '{name}' 初始化并验证通过，注册成功。")
        else:
            logger.warning(f"❌ 引擎 '{name}' 配置检查未通过，注册失败。")

    except Exception as e:
        logger.error(
            f"初始化或验证引擎 {engine_class.__name__} 时发生严重错误: {e}",
            exc_info=True,
        )


# --- 自动导入 ---
# 导入 engines 包，这将触发其 __init__.py 文件中的自动导入逻辑，
# 从而执行所有引擎文件中的 @register_engine 装饰器。
from . import engines  # noqa: E402, F401

# --- 公共API (与之前相同) ---


def list_engines() -> List[str]:
    """返回所有已成功注册的搜索引擎的名称列表。"""
    if not _engine_registry:
        logger.warning(
            "还没有任何搜索引擎被注册或初始化。请先调用 `await search_engine_lib.initialize()`。"
        )
    return list(_engine_registry.keys())


def get_engine(name: str) -> Optional[BaseSearchEngine]:
    """根据名称获取一个已注册的搜索引擎实例。"""
    if not _engine_registry:
        logger.warning(
            "还没有任何搜索引擎被注册或初始化。请先调用 `await search_engine_lib.initialize()`。"
        )

    engine = _engine_registry.get(name)
    if not engine:
        logger.error(f"无法找到名为 '{name}' 的搜索引擎。可用引擎: {list_engines()}")
    return engine
