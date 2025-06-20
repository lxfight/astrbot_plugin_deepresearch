# output_format/manager.py
"""输出格式管理器"""

from typing import Dict, List, Optional, Any
from astrbot.api.star import Star
from astrbot.api import logger

from .base import BaseOutputFormatter
from .formatters import ImageFormatter, MarkdownFormatter, HTMLFormatter
from .svg_formatter import SVGFormatter


class OutputFormatManager:
    """输出格式管理器"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.formatters: Dict[str, BaseOutputFormatter] = {}
        self._initialize_formatters()

    def _initialize_formatters(self):
        """初始化所有格式化器"""
        formatter_classes = [ImageFormatter, MarkdownFormatter, HTMLFormatter, SVGFormatter]

        for formatter_class in formatter_classes:
            try:
                formatter = formatter_class(self.config)
                self.formatters[formatter.format_name] = formatter
                logger.debug(f"[OutputFormat] 初始化格式化器: {formatter.format_name}")
            except Exception as e:
                logger.warning(
                    f"[OutputFormat] 初始化格式化器失败 {formatter_class.__name__}: {e}"
                )

    def get_formatter(self, format_name: str) -> Optional[BaseOutputFormatter]:
        """获取指定的格式化器"""
        return self.formatters.get(format_name)

    def get_available_formats(self) -> List[Dict[str, str]]:
        """获取所有可用的输出格式"""
        return [
            {
                "name": formatter.format_name,
                "description": formatter.description,
                "extension": formatter.file_extension,
            }
            for formatter in self.formatters.values()
        ]

    async def format_report(
        self,
        markdown_content: str,
        format_name: str = "image",
        star_instance: Star = None,
    ) -> Optional[Any]:
        """
        格式化报告

        Args:
            markdown_content: Markdown格式的报告内容
            format_name: 输出格式名称
            star_instance: Star实例，用于某些格式化器

        Returns:
            格式化后的内容
        """
        formatter = self.get_formatter(format_name)
        if not formatter:
            logger.error(f"[OutputFormat] 未找到格式化器: {format_name}")
            return None

        try:
            logger.info(f"[OutputFormat] 使用格式化器 {format_name} 处理报告")
            result = await formatter.format_report(markdown_content, star_instance)

            if result:
                logger.info(f"[OutputFormat] 格式化成功: {format_name}")
            else:
                logger.warning(f"[OutputFormat] 格式化失败: {format_name}")

            return result
        except Exception as e:
            logger.error(
                f"[OutputFormat] 格式化时发生错误 ({format_name}): {e}", exc_info=True
            )
            return None

    def is_format_supported(self, format_name: str) -> bool:
        """检查是否支持指定格式"""
        return format_name in self.formatters

    def get_default_format(self) -> str:
        """获取默认输出格式"""
        return self.config.get("default_output_format", "image")
