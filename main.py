import astrbot.api.star as star
import astrbot.api.event.filter as filter
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api import llm_tool, logger, AstrBotConfig


@star.register(
    name="astrbot-deepresearch",
    desc="让 LLM 具有 deepresearch 能力",
    author="lxfight",
    version="1.919.810",
)
class deepResearch(star.Star):
    """开发版 deepresearch 插件，提供深度研究能力"""

    def __init__(self, context: star.Context, config: AstrBotConfig) -> None:
        self.context = context
        self.config = config
