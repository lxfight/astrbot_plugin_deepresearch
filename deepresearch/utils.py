import re
from pathlib import Path
import uuid
from typing import Optional


class Utils:
    """
    通用工具函数集合。
    """

    @staticmethod
    def cleanup_text(text: Optional[str]) -> Optional[str]:
        """
        清理文本内容，移除多余空白符、HTML标签等。
        这里只做简单处理，实际可能需要更复杂的文本清洗逻辑。
        """
        if not text:
            return None
        # 移除HTML标签（非常简单的实现，可能不完全）
        clean = re.sub(r"<.*?>", "", text)
        # 替换多个空白符为单个空格
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @staticmethod
    def generate_unique_filename(prefix: str = "", suffix: str = "") -> str:
        """
        生成一个唯一的带有前缀和后缀的文件名。
        """
        unique_id = uuid.uuid4().hex[:8]  # 取UUID的前8位作为唯一标识符
        filename = f"{prefix}_{unique_id}{suffix}"
        return filename

    @staticmethod
    def get_file_extension(filename: str) -> str:
        """
        获取文件名的扩展名 (包括点)。
        """
        return Path(filename).suffix.lower()


# Note: URL去重功能已经在 RetrievalPhaseOutput.perform_deduplication 中实现了，
# 但如果需要一个独立的通用URL去重函数，可以这样实现：
# def deduplicate_urls(items: List[RetrievedItem]) -> List[RetrievedItem]:
#     seen_urls = set()
#     unique_items = []
#     for item in items:
#         if item.url not in seen_urls:
#             unique_items.append(item)
#             seen_urls.add(item.url)
#     return unique_items
