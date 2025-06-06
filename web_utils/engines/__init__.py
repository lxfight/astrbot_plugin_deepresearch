# search_engine_lib/engines/__init__.py
import pkgutil
import importlib
from astrbot.api import logger

__path__ = pkgutil.extend_path(__path__, __name__)
for _, module_name, _ in pkgutil.iter_modules(__path__, __name__ + "."):
    try:
        importlib.import_module(module_name)
        logger.debug(f"已自动导入引擎模块: {module_name}")
    except Exception as e:
        logger.error(f"自动导入引擎模块 {module_name} 失败: {e}")
