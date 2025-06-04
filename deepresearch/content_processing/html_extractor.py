import aiohttp
from bs4 import BeautifulSoup, Comment
from typing import Optional
from readability import Document

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.base_module import BaseModule
from deepresearch.utils import Utils


class HTMLExtractor(BaseModule):
    """
    负责从 URL 抓取 HTML 内容并提取主要文本。
    此版本不使用无头浏览器，依赖 aiohttp 获取 HTML，
    并使用 readability-lxml 提取主要内容，辅以 BeautifulSoup 清理。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("HTMLExtractor 模块初始化完成 (轻量级高级版)。")

    async def extract_text(self, url: str) -> Optional[str]:
        """
        从给定的 URL 抓取 HTML 内容，并从中提取主要文本信息。
        使用 aiohttp 获取页面，readability-lxml 提取文章主体，
        BeautifulSoup 清理并获取文本。
        注意：此版本不执行 JavaScript，对于严重依赖JS加载内容的网站可能效果不佳。
        """
        if not url:
            logger.warning("URL 为空，无法提取文本。")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                logger.debug(f"正在抓取 URL: {url}")
                # 添加一些常见的浏览器头部，以减少被简单屏蔽的概率
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
                # 增加超时时间，并允许重定向
                async with session.get(
                    url, timeout=20, headers=headers, allow_redirects=True
                ) as response:
                    response.raise_for_status()  # 检查HTTP响应状态
                    html_content = await response.text()
                    # 记录最终的URL，因为可能发生重定向
                    final_url = str(response.url)
                    if final_url != url:
                        logger.debug(
                            f"URL '{url[:50]}...' 重定向至 '{final_url[:50]}...'"
                        )
                    logger.debug(
                        f"成功获取 URL '{final_url[:50]}...' 的 HTML 内容，状态码: {response.status}"
                    )

            # 使用 readability-lxml 提取主要内容
            doc = Document(html_content)
            article_title = doc.short_title()  # 获取文章标题 (可能为空)
            article_html = doc.summary(
                html_partial=True
            )  # 获取主要内容HTML，html_partial=True更适合片段

            cleaned_text = None
            extraction_source = "未知"  # 用于日志，记录文本来源

            if (
                article_html and len(article_html) > 100
            ):  # 简单判断readability是否提取到有意义的内容
                logger.info(
                    f"Readability 成功从 URL '{final_url[:50]}...' 提取到主要内容 HTML。标题: '{article_title if article_title else '无'}'"
                )
                extraction_source = (
                    f"Readability (标题: {article_title if article_title else '无'})"
                )
                # 使用 BeautifulSoup 从提取出的主要内容HTML中获取纯文本
                soup_article = BeautifulSoup(article_html, "lxml")
                text_content = soup_article.get_text(separator="\n", strip=True)
                cleaned_text = Utils.cleanup_text(text_content)
            else:
                logger.warning(
                    f"Readability 未能从 URL '{final_url[:50]}...' 提取到足够的HTML内容 (或内容过短)。将尝试清理整个页面提取文本。"
                )
                extraction_source = "完整页面清理"
                # 回退策略：使用 BeautifulSoup 清理整个页面并提取文本
                soup_full_page = BeautifulSoup(html_content, "lxml")

                # 移除脚本、样式、头部、脚部、导航、侧边栏、表单等非主体内容
                tags_to_remove_selectors = [
                    "script",
                    "style",
                    "header",
                    "footer",
                    "nav",
                    "aside",
                    "form",
                    "button",
                    ".ad",
                    ".ads",
                    ".advertisement",
                    ".popup",
                    ".cookie-banner",
                    "[aria-hidden='true']",
                ]
                for selector in tags_to_remove_selectors:
                    for unwanted_tag in soup_full_page.select(
                        selector
                    ):  # 使用select更灵活
                        unwanted_tag.extract()

                # 移除HTML注释
                for comment in soup_full_page.find_all(
                    string=lambda text_node: isinstance(text_node, Comment)
                ):
                    comment.extract()

                text_content = soup_full_page.get_text(separator="\n", strip=True)
                if text_content:
                    cleaned_text = Utils.cleanup_text(text_content)
                else:
                    logger.warning(
                        f"即使尝试提取整个页面，也未能从 '{final_url[:50]}...' 获取到有效文本。"
                    )
                    return None

            if cleaned_text:
                logger.info(
                    f"成功从 URL '{final_url[:50]}...' (来源: {extraction_source}) 提取文本，长度：{len(cleaned_text)}"
                )
                return cleaned_text
            else:
                logger.warning(
                    f"未能从 URL '{final_url[:50]}...' (尝试来源: {extraction_source}) 提取到任何有效文本内容。"
                )
                return None

        except aiohttp.ClientResponseError as e:
            logger.warning(
                f"从 URL '{url}' 抓取内容失败 (HTTP 错误 {e.status}): {e.message}"
            )
            return None
        except aiohttp.ClientError as e:  # 包括连接超时、DNS解析失败等
            logger.warning(f"从 URL '{url}' 抓取内容失败 (网络错误): {e}")
            return None
        except Exception as e:
            logger.error(f"从 URL '{url}' 提取文本时发生未知错误: {e}", exc_info=True)
            return None
