# output_format/base.py
"""输出格式化器基类"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from astrbot.api.star import Star


class BaseOutputFormatter(ABC):
    """输出格式化器基类"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    @property
    @abstractmethod
    def format_name(self) -> str:
        """格式名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """格式描述"""
        pass

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """文件扩展名"""
        pass

    @abstractmethod
    async def format_report(
        self, markdown_content: str, star_instance: Star = None
    ) -> Any:
        """
        格式化报告

        Args:
            markdown_content: Markdown格式的报告内容
            star_instance: Star实例，用于调用渲染服务

        Returns:
            格式化后的内容（URL、文件路径、文本等）
        """
        pass

    def validate_content(self, content: str) -> bool:
        """验证内容是否有效"""
        return bool(content and content.strip())
