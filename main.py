from typing import List, Tuple
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

from .core.constants import (
    PLUGIN_NAME,
    PLUGIN_VERSION,
    PLUGIN_DESCRIPTION,
    PLUGIN_AUTHOR,
    PLUGIN_REPO,
)


@register(
    PLUGIN_NAME,
    PLUGIN_AUTHOR,
    PLUGIN_DESCRIPTION,
    PLUGIN_VERSION,
    PLUGIN_REPO,
)
class DeepResearchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def terminate(self):
        logger.info("DeepResearch插件已卸载")
