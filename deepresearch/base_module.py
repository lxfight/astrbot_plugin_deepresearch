from astrbot.api import star, logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent
from typing import List, Dict, Optional, Any


class BaseModule:
    """
    所有 DeepResearch 插件内部模块的基类。
    提供对 AstrBot Context, logger 和插件配置的便捷访问。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        self.context = context
        self.config = config
        self.logger = logger
        self.logger.debug(f"模块 {self.__class__.__name__} 初始化。")
