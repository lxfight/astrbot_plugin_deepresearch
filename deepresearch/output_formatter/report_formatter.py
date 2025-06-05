import markdown
from typing import Union

from astrbot.api import star, logger, AstrBotConfig
# from astrbot.api.star import Context  # 导入 Context 以便调用 html_render
from ..base_module import BaseModule
from ..data_models import ResearchReport


class ReportFormatter(BaseModule):
    """
    负责将研究报告格式化为 HTML 或图片。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("ReportFormatter 模块初始化完成。")

    async def format_report(
        self, report: ResearchReport, format_type: str
    ) -> Union[str, bytes]:
        """
        根据指定格式将报告内容格式化。
        :param report: 要格式化的 ResearchReport 对象。
        :param format_type: 目标格式 ('md', 'html', 'image')。
        :return: 格式化后的字符串 (HTML, Markdown) 或图片URL (字符串)。
        """
        md_content = report.get_full_markdown_content()

        if format_type.lower() == "md":
            return md_content
        elif format_type.lower() == "html":
            return await self._markdown_to_html(md_content)
        elif format_type.lower() == "image":
            return await self._html_to_image(md_content)  # 渲染 Markdown 转换为图片
        else:
            logger.error(f"不支持的报告格式: {format_type}")
            raise ValueError(f"不支持的报告格式: {format_type}")

    async def _markdown_to_html(self, md_content: str) -> str:
        """
        将 Markdown 内容转换为 HTML。
        """
        html_content = markdown.markdown(
            md_content, extensions=["fenced_code", "tables", "nl2br"]
        )
        # 添加一些基本样式，使其更美观
        styled_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{self.config.get("plugin_name", "DeepResearch")} 报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; line-height: 1.6; margin: 20px; padding: 20px; background-color: #f8f8f8; color: #333; }}
  h1, h2, h3, h4, h5, h6 {{ color: #2c3e50; margin-top: 1em; margin-bottom: 0.5em; }}
  h1 {{ font-size: 2.5em; text-align: center; margin-bottom: 1em; }}
  h2 {{ font-size: 2em; border-bottom: 2px solid #eee; padding-bottom: 0.2em; }}
  h3 {{ font-size: 1.5em; }}
  pre {{ background-color: #eee; padding: 1em; border-radius: 5px; overflow-x: auto; }}
  code {{ font-family: monospace; background-color: #eee; padding: 0.2em 0.4em; border-radius: 3px; }}
  a {{ color: #3498db; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  ul {{ list-style-type: disc; margin-left: 20px; }}
  ol {{ list-style-type: decimal; margin-left: 20px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>
{html_content}
</body>
</html>
"""
        logger.debug("Markdown 已转换为 HTML。")
        return styled_html

    async def _html_to_image(self, md_content: str) -> str:
        """
        将 Markdown 内容先转换为 HTML，然后通过 AstrBot 的 html_render 渲染成图片。
        返回图片的 URL。
        """
        html_content = await self._markdown_to_html(md_content)
        try:
            # 需要从 context 中获取主插件实例来调用 html_render
            # 这是一个稍微复杂的地方，因为 html_render 是 Star 类的方法
            # 最佳实践可能是将 html_render 封装到 Context 中，或者提供一个独立的公共服务
            # 暂时通过获取自身的 Star 实例来调用
            deepresearch_plugin_instance = self.context.get_registered_star(
                "astrbot-deepresearch"
            ).star_cls
            if hasattr(deepresearch_plugin_instance, "html_render"):
                image_url = await deepresearch_plugin_instance.html_render(
                    html_content, data={}
                )
                logger.info("HTML 报告已渲染成图片。")
                return image_url
            else:
                logger.error(
                    "DeepResearch 插件实例没有 html_render 方法，无法生成图片。"
                )
                raise RuntimeError("无法调用图片渲染服务。")
        except Exception as e:
            logger.error(f"将 HTML 渲染为图片失败: {e}", exc_info=True)
            raise
