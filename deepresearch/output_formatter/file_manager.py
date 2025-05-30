from pathlib import Path
from typing import Optional
import aiofiles  # 用于异步文件写入

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.base_module import BaseModule
from deepresearch.utils import Utils


class FileManager(BaseModule):
    """
    负责将报告内容保存到本地文件系统，并生成可访问的 URL。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.plugin_data_dir = (
            Path(self.context.get_data_dir())
            / "plugins"
            / "astrbot_deepresearch"
            / "files"
        )
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)  # 确保插件文件目录存在
        logger.info(
            f"FileManager 模块初始化完成。文件存储路径: {self.plugin_data_dir}"
        )

    async def save_text_as_file(
        self, text_content: str, desired_filename: Optional[str] = None
    ) -> str:
        """
        将文本内容保存为文件，并返回其可访问的 URL。
        """
        if not desired_filename:
            desired_filename = Utils.generate_unique_filename(
                prefix="report", suffix=".txt"
            )
        else:
            # 确保文件名是唯一的，防止冲突
            stem = Path(desired_filename).stem
            suffix = Path(desired_filename).suffix
            desired_filename = Utils.generate_unique_filename(
                prefix=stem, suffix=suffix
            )

        file_path = self.plugin_data_dir / desired_filename

        try:
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(text_content)

            # AstrBot通常会提供一个机制来生成本地文件的HTTP访问URL
            # 这里需要一个假设的接口或约定
            # 假设 AstrBot 的文件服务器会将 data/plugins/your_plugin/files 目录下的文件映射到 /files/your_plugin/ 这样的URL
            file_url = f"/files/astrbot_deepresearch/{desired_filename}"  # TODO: 替换为实际的 AstrBot 文件服务器URL生成逻辑

            logger.info(
                f"文件 '{desired_filename}' 已保存到 '{file_path}'，访问 URL: {file_url}"
            )
            return file_url
        except Exception as e:
            logger.error(f"保存文件 '{desired_filename}' 失败: {e}", exc_info=True)
            raise

    # 图片文件可能需要额外的处理，例如直接保存二进制流
    async def save_bytes_as_file(
        self, binary_content: bytes, desired_filename: Optional[str] = None
    ) -> str:
        """
        将二进制内容（如图片）保存为文件，并返回其可访问的 URL。
        """
        if not desired_filename:
            desired_filename = Utils.generate_unique_filename(
                prefix="image", suffix=".bin"
            )

        file_path = self.plugin_data_dir / desired_filename

        try:
            async with aiofiles.open(file_path, mode="wb") as f:
                await f.write(binary_content)

            file_url = f"/files/astrbot_deepresearch/{desired_filename}"  # TODO: 替换为实际的 AstrBot 文件服务器URL生成逻辑

            logger.info(
                f"二进制文件 '{desired_filename}' 已保存到 '{file_path}'，访问 URL: {file_url}"
            )
            return file_url
        except Exception as e:
            logger.error(
                f"保存二进制文件 '{desired_filename}' 失败: {e}", exc_info=True
            )
            raise
