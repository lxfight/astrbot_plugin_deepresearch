from typing import List, Dict

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register

@register(
    "astrbot_plugin_deepresearch",
    "lxfight",
    "一个实现深度研究的AI智能体插件",
    "1.0.0",
    "https://github.com/lxfight/astrbot_plugin_deepresearch",
)
class DeepResearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def terminate(self):
        logger.info("DeepResearch插件已卸载")
