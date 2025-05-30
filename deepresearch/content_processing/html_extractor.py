import aiohttp
from bs4 import BeautifulSoup
from typing import Optional

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.base_module import BaseModule
from deepresearch.utils import Utils


class HTMLExtractor(BaseModule):
    """
    负责从 URL 抓取 HTML 内容并提取主要文本。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("HTMLExtractor 模块初始化完成。")

    async def extract_text(self, url: str) -> Optional[str]:
        """
        从给定的 URL 抓取 HTML 内容，并从中提取主要文本信息。
        这里使用 BeautifulSoup 简单地提取所有可见文本，实际中可能需要更智能的算法（如 readability 库）。
        """
        if not url:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                logger.debug(f"正在抓取 URL: {url}")
                async with session.get(url, timeout=15) as response:
                    response.raise_for_status()  # 检查HTTP响应状态
                    html_content = await response.text()

            soup = BeautifulSoup(html_content, "lxml")  # 使用 lxml 解析器更快

            # 移除脚本和样式
            for script in soup(["script", "style"]):
                script.extract()

            # 获取所有可见文本
            text = soup.get_text()

            # 清理文本，去除多余空白符
            cleaned_text = Utils.cleanup_text(text)
            logger.info(
                f"成功从 URL '{url[:50]}...' 提取文本，长度：{len(cleaned_text) if cleaned_text else 0}"
            )
            return cleaned_text

        except aiohttp.ClientError as e:
            logger.warning(f"从 URL '{url}' 抓取内容失败 (网络错误): {e}")
            return None
        except Exception as e:
            logger.error(f"从 URL '{url}' 提取文本失败: {e}", exc_info=True)
            return None
