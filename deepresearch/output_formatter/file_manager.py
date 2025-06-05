from pathlib import Path
from typing import Optional, Dict, Any
import aiofiles  # 用于异步文件写入
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
import mimetypes

from astrbot.api.star import StarTools
from astrbot.api import star, logger, AstrBotConfig
from ..base_module import BaseModule
from ..utils import Utils
from ..constants import PLUGIN_NAME


class FileManager(BaseModule):
    """
    负责将报告内容保存到本地文件系统，并生成可访问的 URL。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.plugin_data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME)) / "files"
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)  # 确保插件文件目录存在

        # 文件清理配置
        self.file_retention_hours = config.get("output_config", {}).get(
            "temp_file_retention_hours", 24
        )
        self.max_file_size_mb = 50  # 最大文件大小限制

        # 文件映射记录
        self.file_registry_path = self.plugin_data_dir / "file_registry.json"
        self.file_registry: Dict[str, Any] = {}

        # 启动时加载文件注册表和清理过期文件
        asyncio.create_task(self._initialize_file_registry())

        logger.info(f"FileManager 模块初始化完成。文件存储路径: {self.plugin_data_dir}")

    async def _initialize_file_registry(self):
        """初始化文件注册表并清理过期文件"""
        try:
            if self.file_registry_path.exists():
                async with aiofiles.open(
                    self.file_registry_path, "r", encoding="utf-8"
                ) as f:
                    content = await f.read()
                    self.file_registry = json.loads(content) if content else {}

            # 清理过期文件
            await self._cleanup_expired_files()

        except Exception as e:
            logger.error(f"初始化文件注册表时出错: {e}", exc_info=True)
            self.file_registry = {}

    async def _save_file_registry(self):
        """保存文件注册表"""
        try:
            async with aiofiles.open(
                self.file_registry_path, "w", encoding="utf-8"
            ) as f:
                await f.write(
                    json.dumps(self.file_registry, ensure_ascii=False, indent=2)
                )
        except Exception as e:
            logger.error(f"保存文件注册表时出错: {e}", exc_info=True)

    async def _cleanup_expired_files(self):
        """清理过期文件"""
        try:
            current_time = datetime.now()
            expired_files = []

            for file_id, file_info in list(self.file_registry.items()):
                created_time = datetime.fromisoformat(file_info.get("created_at", ""))
                if current_time - created_time > timedelta(
                    hours=self.file_retention_hours
                ):
                    file_path = Path(file_info.get("file_path", ""))
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            logger.info(f"已删除过期文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"删除过期文件失败 {file_path}: {e}")
                    expired_files.append(file_id)

            # 从注册表中移除过期文件记录
            for file_id in expired_files:
                del self.file_registry[file_id]

            if expired_files:
                await self._save_file_registry()
                logger.info(f"清理了 {len(expired_files)} 个过期文件")

        except Exception as e:
            logger.error(f"清理过期文件时出错: {e}", exc_info=True)

    def _generate_file_id(self, content: str) -> str:
        """根据内容生成文件ID"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

    def _validate_file_size(self, content_size: int) -> bool:
        """验证文件大小"""
        max_size_bytes = self.max_file_size_mb * 1024 * 1024
        return content_size <= max_size_bytes

    async def save_text_as_file(
        self,
        text_content: str,
        desired_filename: Optional[str] = None,
        file_type: str = "txt",
    ) -> Dict[str, Any]:
        """
        将文本内容保存为文件，并返回文件信息。

        Returns:
            Dict containing file_url, file_id, file_path, and metadata
        """
        if not text_content:
            raise ValueError("文本内容不能为空")

        # 验证文件大小
        content_size = len(text_content.encode("utf-8"))
        if not self._validate_file_size(content_size):
            raise ValueError(f"文件大小超过限制 ({self.max_file_size_mb}MB)")

        # 生成文件ID
        file_id = self._generate_file_id(text_content)

        # 检查是否已存在相同内容的文件
        if file_id in self.file_registry:
            logger.info(f"复用现有文件: {file_id}")
            return self.file_registry[file_id]

        if not desired_filename:
            desired_filename = Utils.generate_unique_filename(
                prefix="report", suffix=f".{file_type}"
            )
        else:
            # 确保文件名是唯一的，防止冲突
            stem = Path(desired_filename).stem
            suffix = Path(desired_filename).suffix or f".{file_type}"
            desired_filename = Utils.generate_unique_filename(
                prefix=stem, suffix=suffix
            )

        file_path = self.plugin_data_dir / desired_filename

        try:
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(text_content)

            # 生成文件访问URL
            file_url = f"/files/astrbot_deepresearch/{desired_filename}"

            # 记录文件信息
            file_info = {
                "file_id": file_id,
                "file_url": file_url,
                "file_path": str(file_path),
                "filename": desired_filename,
                "file_type": file_type,
                "content_size": content_size,
                "mime_type": mimetypes.guess_type(desired_filename)[0] or "text/plain",
                "created_at": datetime.now().isoformat(),
                "expires_at": (
                    datetime.now() + timedelta(hours=self.file_retention_hours)
                ).isoformat(),
            }

            self.file_registry[file_id] = file_info
            await self._save_file_registry()

            logger.info(
                f"文件 '{desired_filename}' 已保存，ID: {file_id}, URL: {file_url}"
            )
            return file_info

        except Exception as e:
            logger.error(f"保存文件 '{desired_filename}' 失败: {e}", exc_info=True)
            # 清理可能创建的文件
            if file_path.exists():
                try:
                    file_path.unlink()
                except:
                    pass
            raise

    async def save_bytes_as_file(
        self,
        binary_content: bytes,
        desired_filename: Optional[str] = None,
        file_type: str = "bin",
    ) -> Dict[str, Any]:
        """
        将二进制内容（如图片）保存为文件，并返回文件信息。
        """
        if not binary_content:
            raise ValueError("二进制内容不能为空")

        # 验证文件大小
        if not self._validate_file_size(len(binary_content)):
            raise ValueError(f"文件大小超过限制 ({self.max_file_size_mb}MB)")

        # 生成文件ID
        file_id = hashlib.md5(binary_content).hexdigest()[:16]

        # 检查是否已存在相同内容的文件
        if file_id in self.file_registry:
            logger.info(f"复用现有二进制文件: {file_id}")
            return self.file_registry[file_id]

        if not desired_filename:
            desired_filename = Utils.generate_unique_filename(
                prefix="binary", suffix=f".{file_type}"
            )

        file_path = self.plugin_data_dir / desired_filename

        try:
            async with aiofiles.open(file_path, mode="wb") as f:
                await f.write(binary_content)

            file_url = f"/files/astrbot_deepresearch/{desired_filename}"

            # 记录文件信息
            file_info = {
                "file_id": file_id,
                "file_url": file_url,
                "file_path": str(file_path),
                "filename": desired_filename,
                "file_type": file_type,
                "content_size": len(binary_content),
                "mime_type": mimetypes.guess_type(desired_filename)[0]
                or "application/octet-stream",
                "created_at": datetime.now().isoformat(),
                "expires_at": (
                    datetime.now() + timedelta(hours=self.file_retention_hours)
                ).isoformat(),
            }

            self.file_registry[file_id] = file_info
            await self._save_file_registry()

            logger.info(
                f"二进制文件 '{desired_filename}' 已保存，ID: {file_id}, URL: {file_url}"
            )
            return file_info

        except Exception as e:
            logger.error(
                f"保存二进制文件 '{desired_filename}' 失败: {e}", exc_info=True
            )
            # 清理可能创建的文件
            if file_path.exists():
                try:
                    file_path.unlink()
                except:
                    pass
            raise

    async def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取文件信息"""
        return self.file_registry.get(file_id)

    async def delete_file(self, file_id: str) -> bool:
        """删除指定文件"""
        try:
            if file_id not in self.file_registry:
                return False

            file_info = self.file_registry[file_id]
            file_path = Path(file_info.get("file_path", ""))

            if file_path.exists():
                file_path.unlink()

            del self.file_registry[file_id]
            await self._save_file_registry()

            logger.info(f"已删除文件: {file_id}")
            return True

        except Exception as e:
            logger.error(f"删除文件失败 {file_id}: {e}", exc_info=True)
            return False

    async def cleanup_all_files(self):
        """清理所有文件（用于插件卸载时）"""
        try:
            for file_info in self.file_registry.values():
                file_path = Path(file_info.get("file_path", ""))
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as e:
                        logger.warning(f"清理文件时出错 {file_path}: {e}")

            self.file_registry.clear()

            # 清理注册表文件
            if self.file_registry_path.exists():
                self.file_registry_path.unlink()

            logger.info("所有文件已清理完毕")

        except Exception as e:
            logger.error(f"清理所有文件时出错: {e}", exc_info=True)
