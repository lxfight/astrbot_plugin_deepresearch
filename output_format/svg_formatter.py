# output_format/svg_formatter.py
"""SVG格式化器实现"""

import os
import re
import tempfile
import datetime
import html
from typing import Dict, Optional, List, TypedDict
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from astrbot.api.star import Star
from astrbot.api import logger

from .base import BaseOutputFormatter


# 定义类型
class MarkdownSection(TypedDict):
    id: str
    title: str
    level: int
    content_html: str


class SVGFormatter(BaseOutputFormatter):
    """SVG格式化器 - 生成精美的HTML报告，不包含复杂的引用处理"""

    @property
    def format_name(self) -> str:
        return "html"

    @property
    def description(self) -> str:
        return "生成精美的HTML报告文件"

    @property
    def file_extension(self) -> str:
        return ".html"

    # MODIFICATION START: 新增异步获取网页标题的方法
    async def _fetch_link_title(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[str]:
        """异步获取给定URL的网页标题"""
        try:
            # 设置合理的超时时间，防止长时间等待
            async with session.get(url, timeout=10, ssl=False) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, "html.parser")
                    if soup.title and soup.title.string:
                        # 清理标题并截断过长的标题
                        title = soup.title.string.strip()
                        if len(title) > 40:
                            title = title[:38] + "…"
                        return title
        except asyncio.TimeoutError:
            logger.warning(f"[SVGFormatter] 获取URL标题超时: {url}")
        except aiohttp.ClientError as e:
            logger.warning(
                f"[SVGFormatter] 获取URL标题时发生网络错误: {url}, 错误: {e}"
            )
        except Exception as e:
            logger.error(
                f"[SVGFormatter] 解析URL时发生未知错误: {url}, 错误: {e}",
                exc_info=False,
            )
        return None  # 如果失败则返回None

    # MODIFICATION END

    async def format_report(
        self, markdown_content: str, star_instance: Star = None
    ) -> Optional[str]:
        if not self.validate_content(markdown_content):
            logger.warning("[SVGFormatter] Markdown内容为空")
            return None
        # 检查依赖库是否已安装
        if not all([aiohttp, BeautifulSoup]):
            logger.error(
                "[SVGFormatter] 依赖库 'aiohttp' 或 'beautifulsoup4' 未安装。无法解析链接标题。"
            )
            return None

        try:
            # 预处理：将文本形式的换行符转换为真实换行符
            processed_content = self._preprocess_content(markdown_content)

            # MODIFICATION START: 异步获取所有来源链接的标题
            url_to_title_map: Dict[str, str] = {}
            # 使用正则表达式找出所有唯一的来源URL
            source_urls = list(
                set(re.findall(r"\[来源:\s+(https?://[^\]]+)\]", processed_content))
            )

            if source_urls:
                logger.info(
                    f"[SVGFormatter] 发现 {len(source_urls)} 个来源链接，开始异步获取标题..."
                )
                async with aiohttp.ClientSession() as session:
                    # 创建并发任务
                    tasks = [
                        self._fetch_link_title(session, url) for url in source_urls
                    ]
                    # 等待所有任务完成
                    titles = await asyncio.gather(*tasks)
                    # 构建URL到标题的映射字典，只包含成功获取的标题
                    url_to_title_map = {
                        url: title for url, title in zip(source_urls, titles) if title
                    }
                logger.info(f"[SVGFormatter] 成功获取 {len(url_to_title_map)} 个标题。")
            # MODIFICATION END

            # MODIFICATION: 将获取到的标题字典传递给解析函数
            sections = self._parse_markdown_to_sections(
                processed_content, url_to_title_map
            )

            html_content = self._generate_html_report(sections)
            temp_file = self._save_to_temp_file(html_content)
            logger.info("[SVGFormatter] HTML报告生成成功")
            return temp_file
        except Exception as e:
            logger.error(f"[SVGFormatter] 生成HTML报告时发生错误: {e}", exc_info=True)
            return None

    def _preprocess_content(self, markdown_content: str) -> str:
        """
        预处理Markdown内容，将文本形式的换行符转换为真实换行符
        """
        # 将文本形式的 \n 转换为真实的换行符
        processed = markdown_content.replace("\\n", "\n")

        # 将文本形式的 \t 转换为真实的制表符
        processed = processed.replace("\\t", "\t")

        # 将文本形式的 \r 转换为真实的回车符（如果存在）
        processed = processed.replace("\\r", "\r")

        # 清理多余的空行（超过2个连续换行符的情况）
        processed = re.sub(r"\n{3,}", "\n\n", processed)

        # 去除行尾多余的空格
        processed = re.sub(r"[ \t]+\n", "\n", processed)

        # 去除开头和结尾的空白字符
        processed = processed.strip()

        logger.info(f"[SVGFormatter] 预处理完成，内容长度: {len(processed)}")
        return processed

    def _slugify(self, text: str) -> str:
        """生成URL友好的ID"""
        s = text.strip().lower()
        s = re.sub(r"[\s\(\)（）]+", "-", s)
        s = re.sub(r"[^\w\-_]", "", s)
        return s if s else "section"

    # MODIFICATION: 修改函数签名，接收标题字典
    def _render_markdown(self, raw_text: str, url_to_title_map: Dict[str, str]) -> str:
        """
        增强的Markdown渲染函数，支持代码块、多级标题和来源链接
        """
        import uuid

        # 用于存储占位符
        placeholders = {}
        # 用于来源链接的计数器，以生成唯一编号
        source_link_index = 0

        # 1. 先处理代码块（在HTML转义之前处理）
        def code_block_replacer(match):
            language = match.group(1) if match.group(1) else "text"
            code_content = match.group(2)
            # 对代码内容进行HTML转义
            escaped_code = html.escape(code_content)

            # 语言名称映射和标准化
            language_map = {
                "py": "python",
                "js": "javascript",
                "ts": "typescript",
                "sh": "bash",
                "shell": "bash",
                "yml": "yaml",
                "json": "json",
                "xml": "xml",
                "html": "markup",
                "css": "css",
                "scss": "scss",
                "sql": "sql",
                "java": "java",
                "cpp": "cpp",
                "c": "c",
                "go": "go",
                "rust": "rust",
                "php": "php",
            }

            normalized_lang = language_map.get(language.lower(), language.lower())
            display_lang = language.upper() if language else "TEXT"

            # 添加语言标识属性
            code_html = f'<pre class="language-{normalized_lang}" data-language="{display_lang}"><code class="language-{normalized_lang}">{escaped_code}</code></pre>'
            placeholder = f"CODEBLOCK{uuid.uuid4().hex}ENDCODE"
            placeholders[placeholder] = code_html
            return placeholder

        # 匹配 ```language 和 ``` 包围的代码块
        text = re.sub(
            r"```(\w+)?\n(.*?)\n```", code_block_replacer, raw_text, flags=re.DOTALL
        )

        # MODIFICATION START: 修改来源链接的处理逻辑以使用获取到的标题
        # 2. 提取并处理来源链接
        def link_replacer(match):
            nonlocal source_link_index
            source_link_index += 1
            url = match.group(1)

            # 从字典中获取标题，如果找不到，则使用 "来源" 作为后备
            link_text = url_to_title_map.get(url, "来源")

            # 构造favicon的URL
            favicon_url = f"https://www.google.com/s2/favicons?sz=16&domain_url={html.escape(url)}"

            # 生成HTML。onerror事件处理图标加载失败，title属性提供完整URL和编号。
            # link_text现在是动态获取的标题
            link_html = f"""<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer" class="source-link" title="{html.escape(link_text)} - {html.escape(url)}">
    <img src="{favicon_url}" class="source-favicon" alt="图标" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';">
    <span class="source-fallback-number" style="display: none;">{source_link_index}</span>
    <span class="source-text">{html.escape(link_text)}</span>
</a>"""
            # 移除HTML片段中的换行符和多余空格
            link_html = re.sub(r"\s*\n\s*", " ", link_html).strip()

            placeholder = f"LINKPLACEHOLDER{uuid.uuid4().hex}ENDLINK"
            placeholders[placeholder] = link_html
            return placeholder

        text = re.sub(r"\[来源:\s+(https?://[^\]]+)\]", link_replacer, text)
        # MODIFICATION END

        # 3. HTML转义（保护占位符）
        escaped_text = html.escape(text)

        # 4. 按段落分割处理
        paragraphs = escaped_text.split("\n\n")
        html_paragraphs = []

        for para in paragraphs:
            if not para.strip():
                continue

            # 按行处理段落内的Markdown
            lines = para.split("\n")
            processed_lines = []
            in_list = False

            for line in lines:
                stripped_line = line.lstrip()

                # 处理标题
                if stripped_line.startswith("######"):
                    processed_lines.append(f"<h6>{stripped_line[6:].strip()}</h6>")
                    continue
                elif stripped_line.startswith("#####"):
                    processed_lines.append(f"<h5>{stripped_line[5:].strip()}</h5>")
                    continue
                elif stripped_line.startswith("####"):
                    processed_lines.append(f"<h4>{stripped_line[4:].strip()}</h4>")
                    continue
                elif stripped_line.startswith("###"):
                    processed_lines.append(f"<h3>{stripped_line[3:].strip()}</h3>")
                    continue
                elif stripped_line.startswith("##"):
                    processed_lines.append(f"<h2>{stripped_line[2:].strip()}</h2>")
                    continue
                elif stripped_line.startswith("#"):
                    processed_lines.append(f"<h1>{stripped_line[1:].strip()}</h1>")
                    continue

                # 处理列表
                is_list_item = stripped_line.startswith(("- ", "* ", "+ "))
                if is_list_item and not in_list:
                    processed_lines.append("<ul>")
                    in_list = True
                if not is_list_item and in_list:
                    processed_lines.append("</ul>")
                    in_list = False

                if is_list_item:
                    item_content = re.sub(r"^[-*+]\s*", "", stripped_line)
                    processed_lines.append(f"<li>{item_content}</li>")
                else:
                    processed_lines.append(line)

            if in_list:
                processed_lines.append("</ul>")

            para_content = "\n".join(processed_lines)

            # 处理行内Markdown格式
            para_content = re.sub(
                r"\*\*(.*?)\*\*", r"<strong>\1</strong>", para_content
            )
            para_content = re.sub(r"__(.*?)__", r"<strong>\1</strong>", para_content)
            para_content = re.sub(
                r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", para_content
            )
            para_content = re.sub(r"(?<!_)_([^_]+)_(?!_)", r"<em>\1</em>", para_content)
            para_content = re.sub(r"~~(.*?)~~", r"<del>\1</del>", para_content)
            para_content = re.sub(r"`([^`]+)`", r"<code>\1</code>", para_content)
            para_content = re.sub(
                r"\[([^\]]+)\]\((https?://[^\)]+)\)",
                r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
                para_content,
            )

            if not re.match(r"^\s*<(h[1-6]|ul|li)", para_content.lstrip()):
                para_content = f"<p>{para_content.replace(chr(10), '<br>')}</p>"

            html_paragraphs.append(para_content)

        final_html = "\n".join(html_paragraphs)

        # 清理HTML结构
        final_html = re.sub(
            r"<p>(<ul>.*?</ul>)</p>", r"\1", final_html, flags=re.DOTALL
        )
        final_html = re.sub(
            r"<p>(<h[1-6]>.*?</h[1-6]>)</p>", r"\1", final_html, flags=re.DOTALL
        )
        final_html = re.sub(
            r"<p>(<pre>.*?</pre>)</p>", r"\1", final_html, flags=re.DOTALL
        )
        final_html = final_html.replace("<p><br>", "<p>")
        final_html = final_html.replace("<br></p>", "</p>")
        final_html = re.sub(r"<br>\s*<(ul|/ul|li|h[1-6]|pre)", r"<\1", final_html)

        for placeholder, content in placeholders.items():
            escaped_placeholder = html.escape(placeholder)
            final_html = final_html.replace(escaped_placeholder, content)

        return final_html

    # MODIFICATION: 修改函数签名，接收标题字典
    def _parse_markdown_to_sections(
        self, markdown_content: str, url_to_title_map: Dict[str, str]
    ) -> List[MarkdownSection]:
        """将Markdown解析成章节 - 只有H2作为章节卡片，H3及以下在卡片内"""
        sections: List[MarkdownSection] = []
        has_h2 = bool(re.search(r"^##\s+", markdown_content, re.MULTILINE))
        primary_delimiter_raw = "##" if has_h2 else "###"
        primary_delimiter_re = re.escape(primary_delimiter_raw)
        split_marker = "\n__SECTION_SPLIT__\n"
        content_with_markers = re.sub(
            f"^{primary_delimiter_re}\\s+(.*)",
            f"{split_marker}{primary_delimiter_raw} \\1",
            markdown_content,
            flags=re.MULTILINE,
        )
        raw_sections = content_with_markers.split(split_marker)
        intro_content = raw_sections.pop(0).strip()

        if intro_content:
            main_title_match = re.match(r"^#\s+(.*)", intro_content)
            if main_title_match:
                main_title_text = main_title_match.group(1).strip()
                intro_body = intro_content[main_title_match.end() :].strip()
                full_intro = f"# {main_title_text}\n\n{intro_body}"
            else:
                full_intro = intro_content

            # MODIFICATION: 传递标题字典
            content_html = self._render_markdown(full_intro, url_to_title_map)
            sections.append(
                MarkdownSection(
                    id="introduction",
                    title="报告概述",
                    level=1,
                    content_html=content_html,
                )
            )

        used_ids = set(["introduction"])

        for raw_section in raw_sections:
            if not raw_section.strip():
                continue

            lines = raw_section.strip().split("\n", 1)
            if not lines[0].startswith(primary_delimiter_raw):
                continue

            title = lines[0][len(primary_delimiter_raw) :].strip()
            content_md = lines[1] if len(lines) > 1 else ""

            # MODIFICATION: 传递标题字典
            content_html = self._render_markdown(content_md, url_to_title_map)

            base_id = self._slugify(title)
            unique_id = base_id
            count = 1
            while unique_id in used_ids:
                unique_id = f"{base_id}-{count}"
                count += 1
            used_ids.add(unique_id)

            sections.append(
                MarkdownSection(
                    id=unique_id,
                    title=title,
                    level=2 if has_h2 else 3,
                    content_html=content_html,
                )
            )

        return sections

    # 剩下的 `_generate_html_report` 及之后的方法保持不变，因为之前的CSS已经足够灵活，
    # 只需要我们通过Python生成正确的HTML即可。
    # 为确保完整性，在此处粘贴未变动的代码。

    def _generate_html_report(self, sections: List[MarkdownSection]) -> str:
        """生成完整的HTML报告 (注入了丰富的动画特效)"""
        # 为目录项添加动画延迟
        toc_html = "".join(
            f'<li style="--anim-delay: {i * 0.05}s;"><a href="#{s["id"]}">{html.escape(s["title"])}</a></li>'
            for i, s in enumerate(sections)
        )

        # 提取主标题作为侧边栏标题
        sidebar_title = "AI研究报告"
        if (
            sections
            and sections[0]["id"] == "introduction"
            and sections[0]["content_html"]
        ):
            # 从第一个章节的HTML中提取h1标题
            h1_match = re.search(
                r"<h1>(.*?)</h1>", sections[0]["content_html"], re.DOTALL
            )
            if h1_match:
                # 清理HTML标签并提取纯文本
                clean_title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
                if clean_title:
                    sidebar_title = html.escape(clean_title) + " - 研究报告"

        cards_html = ""
        for i, section in enumerate(sections):
            section_id = section["id"]
            escaped_title = html.escape(section["title"])

            # 为标题的每个字符包裹<span>，用于动画
            title_spans = "".join(
                f'<span class="char" style="--char-delay: {j * 0.03}s;">{char}</span>'
                for j, char in enumerate(escaped_title)
            )

            # 报告概述使用H1，其他章节使用H2作为卡片标题
            title_tag = "h1" if section["id"] == "introduction" else "h2"
            section_title_html = f'<{title_tag} class="card-title" data-title="{escaped_title}">{title_spans}</{title_tag}>'

            section_content = section["content_html"]

            # 对于报告概述卡片，我们不希望在内容区重复显示H1标题
            if section["id"] == "introduction":
                section_content = re.sub(
                    r"<h1[^>]*>.*?</h1>", "", section_content, count=1
                ).strip()

            cards_html += f"""
            <section class="report-card scroll-reveal" id="{section_id}">
                {section_title_html}
                <div class="card-content">
                    {section_content}
                </div>
            </section>
            """

        # 使用f-string并转义CSS/JS中的花括号
        return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AstrBot - deepresearch 插件制作</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel="stylesheet">
    <!-- Prism.js 代码高亮 -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" rel="stylesheet">
    <style>
        /* --- 全局与基础样式 --- */
        :root {{
            --bg-main: #f9fafb;
            --bg-sidebar: #ffffff;
            --bg-card: #ffffff;
            --text-primary: #111827;
            --text-secondary: #6b7280;
            --accent-color: #3b82f6;
            --accent-color-light: #eff6ff;
            --border-color: #e5e7eb;
            --shadow-color: rgba(0, 0, 0, 0.04);
            --font-sans: 'Inter', 'Noto Sans SC', sans-serif;
            --card-glow-color: rgba(59, 130, 246, 0.2);
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: var(--font-sans); background-color: var(--bg-main);
            color: var(--text-primary); line-height: 1.8; font-size: 16px;
            -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
            overflow-x: hidden; /* 防止动画溢出 */
        }}

        /* --- 鼠标追随光标特效 --- */
        .cursor-glow {{
            position: fixed;
            top: 0;
            left: 0;
            width: 500px;
            height: 500px;
            border-radius: 50%;
            background: radial-gradient(circle, var(--accent-color) 0%, rgba(255,255,255,0) 60%);
            pointer-events: none;
            mix-blend-mode: screen;
            opacity: 0.1;
            z-index: 9999;
            transform: translate(-50%, -50%);
            transition: transform 0.1s ease-out, opacity 0.3s;
        }}

        /* --- 布局 --- */
        .container {{ display: flex; max-width: 1600px; margin: 0 auto; }}
        .sidebar {{
            width: 280px; position: sticky; top: 0; height: 100vh;
            background: var(--bg-sidebar); border-right: 1px solid var(--border-color);
            padding: 32px 0; flex-shrink: 0; overflow-y: auto;
        }}
        main.content {{ flex-grow: 1; padding: 48px 6%; }}

        /* --- 侧边栏与目录 (TOC) 动画 --- */
        .sidebar-header {{ padding: 0 24px; margin-bottom: 24px; }}
        .sidebar-header h1 {{ 
            font-size: 1.4em; font-weight: 700;
            background: linear-gradient(90deg, var(--accent-color), #111827);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .toc {{ padding: 0 24px; }}
        .toc h3 {{ font-size: 0.8em; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 12px; font-weight: 600; }}
        .toc ul {{ list-style: none; }}
        .toc li {{
            opacity: 0;
            transform: translateX(-20px);
            animation: slide-in 0.4s ease-out forwards;
            animation-delay: var(--anim-delay, 0s);
        }}
        @keyframes slide-in {{
            to {{ opacity: 1; transform: translateX(0); }}
        }}
        .toc li a {{
            color: #374151; text-decoration: none; display: block;
            padding: 8px 12px; border-radius: 6px; transition: all 0.2s ease;
            font-size: 0.9em; border-left: 2px solid transparent;
        }}
        .toc li a:hover {{ background-color: #f3f4f6; color: var(--text-primary); }}
        .toc li a.active {{
            background-color: var(--accent-color-light); color: var(--accent-color); 
            font-weight: 600; border-left-color: var(--accent-color);
        }}

        /* --- 内容卡片 (动画与交互) --- */
        .report-card {{
            background-color: var(--bg-card);
            border-radius: 16px; /* 更大的圆角 */
            margin-bottom: 48px;
            border: 1px solid var(--border-color);
            transform-style: preserve-3d;
            transition: transform 0.4s ease-out, box-shadow 0.4s ease-out, opacity 0.6s ease-out;
            opacity: 1; /* 默认可见 */
            transform: translateY(0);
            will-change: transform, opacity; /* 性能优化 */
            box-shadow: 0 2px 8px var(--shadow-color); /* 默认阴影 */
        }}
        .report-card.scroll-reveal {{
            opacity: 0;
            transform: translateY(40px);
        }}
        .report-card.in-view {{
            opacity: 1;
            transform: translateY(0);
        }}
        .report-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px -5px rgba(59, 130, 246, 0.15), 0 0 0 3px var(--card-glow-color);
            border-color: var(--accent-color);
        }}
        .card-body {{ padding: 32px 40px; }}
        
        /* 卡片跳转高亮动画 */
        @keyframes highlight-card {{
            0% {{ box-shadow: 0 2px 8px var(--shadow-color), 0 0 0 0px var(--card-glow-color); }}
            50% {{ box-shadow: 0 5px 15px var(--shadow-color), 0 0 0 8px var(--card-glow-color); }}
            100% {{ box-shadow: 0 2px 8px var(--shadow-color), 0 0 0 0px var(--card-glow-color); }}
        }}
        .report-card.highlight {{
            animation: highlight-card 1s ease-out;
        }}

        /* 卡片标题字符动画 */
        .card-title {{
            padding: 32px 40px 0; /* 调整padding */
            margin-bottom: 24px;
            font-size: 1.8em;
            color: var(--text-primary);
            font-weight: 700;
            line-height: 1.3;
        }}
        .card-title .char {{
            display: inline-block;
            opacity: 0;
            transform: translateY(20px) scale(0.8) rotate(10deg);
            animation: char-reveal 0.6s ease forwards;
            animation-delay: var(--char-delay, 0s);
        }}
        @keyframes char-reveal {{
            to {{
                opacity: 1;
                transform: translateY(0) scale(1) rotate(0);
            }}
        }}
        /* 为滚动动画保留的备用触发 */
        .report-card.in-view .card-title .char {{
            animation-play-state: running;
        }}

        /* --- 卡片内容区域 --- */
        .card-content {{ padding: 0 40px 32px; }}
        .card-content > *:first-child {{ margin-top: 0; }}
        .card-content > *:last-child {{ margin-bottom: 0; }}

        .card-content h1, .card-content h2, .card-content h3, .card-content h4, .card-content h5, .card-content h6 {{
            margin-top: 2.2em; margin-bottom: 1em; line-height: 1.4; color: var(--text-primary);
        }}
        .card-content h1 {{ font-size: 1.5em; font-weight: 600; }}
        .card-content h2 {{ font-size: 1.35em; font-weight: 600; border-bottom: 1px solid #f3f4f6; padding-bottom: 0.4em; }}
        
        .card-content h3 {{ font-size: 1.25em; font-weight: 700; color: var(--text-primary); margin-top: 2.5em; margin-bottom: 1.2em; border-left: 4px solid var(--accent-color); padding-left: 12px; }}
        .card-content h4 {{ font-size: 1.15em; font-weight: 700; color: #374151; margin-top: 2.2em; margin-bottom: 1.1em; padding-bottom: 0.3em; border-bottom: 1px dashed var(--border-color); }}
        .card-content h5 {{ font-size: 1.05em; font-weight: 700; color: #4b5563; margin-top: 2em; margin-bottom: 1em; }}
        .card-content h6 {{ font-size: 1.0em; font-weight: 700; color: var(--text-secondary); margin-top: 1.8em; margin-bottom: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; }}
        .card-content p {{ margin-bottom: 1.25em; color: var(--text-secondary); }}
        .card-content strong {{ color: var(--text-primary); font-weight: 600; }}
        .card-content a {{
            color: var(--accent-color); text-decoration: none;
            background-image: linear-gradient(to top, var(--accent-color-light) 50%, transparent 50%);
            background-size: 100% 200%; background-position: 0 0;
            transition: background-position 0.3s ease;
        }}
        .card-content a:hover {{ background-position: 0 100%; }}
        .card-content ul {{ list-style: none; padding-left: 0; margin-bottom: 1.25em; }}
        .card-content li {{ position: relative; padding-left: 24px; margin-bottom: 0.75em; color: var(--text-secondary); }}
        .card-content li::before {{ content: ''; position: absolute; left: 4px; top: 10px; width: 6px; height: 6px; background-color: var(--accent-color); border-radius: 50%; }}
        .card-content code {{ font-family: 'SF Mono', 'Menlo', monospace; background-color: #f3f4f6; padding: 0.2em 0.5em; border-radius: 6px; font-size: 0.9em; color: #be123c; border: 1px solid var(--border-color); }}
        
        /* 来源链接样式 (之前已添加，无需修改) */
        .card-content a.source-link {{
            display: inline-flex; align-items: center; gap: 6px;
            background-color: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 9999px;
            padding: 3px 10px 3px 5px; font-size: 0.85em; font-weight: 500;
            color: #4b5563; text-decoration: none; vertical-align: middle;
            margin: 0 2px; background-image: none; transition: all 0.2s ease;
            max-width: 300px; /* 限制最大宽度，防止过长标题破坏布局 */
        }}
        .card-content a.source-link:hover {{
            background-color: #e5e7eb; border-color: #d1d5db; color: #1f2937;
            transform: translateY(-1px); box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            background-position: initial;
        }}
        .source-favicon {{ width: 16px; height: 16px; border-radius: 50%; object-fit: contain; background-color: #fff; flex-shrink: 0; }}
        .source-fallback-number {{
            display: none; width: 16px; height: 16px; border-radius: 50%;
            background-color: var(--accent-color); color: white; font-size: 10px;
            font-weight: bold; line-height: 16px; text-align: center;
            flex-shrink: 0; align-items: center; justify-content: center;
        }}
        .source-text {{
            line-height: 1;
            white-space: nowrap; /* 防止文本换行 */
            overflow: hidden; /* 隐藏溢出的文本 */
            text-overflow: ellipsis; /* 使用省略号显示被截断的文本 */
        }}
        
        /* 代码高亮增强样式 */
        .card-content pre {{ background-color: #2d3748; border-radius: 12px; padding: 1.5em; margin: 1.5em 0; overflow-x: auto; border: 1px solid #4a5568; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); position: relative; }}
        .card-content pre code {{ background-color: transparent; padding: 0; border: none; color: #e2e8f0; font-size: 0.9em; line-height: 1.6; font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace; }}
        .card-content pre::before {{ content: attr(data-language); position: absolute; top: 0.5em; right: 1em; color: #a0aec0; font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.1em; }}
        pre[class*="language-"] {{ background: #2d3748 !important; border: 1px solid #4a5568 !important; }}
        .token.comment, .token.prolog, .token.doctype, .token.cdata {{ color: #718096; }}
        .token.punctuation {{ color: #e2e8f0; }}
        .token.property, .token.tag, .token.boolean, .token.number, .token.constant, .token.symbol, .token.deleted {{ color: #f56565; }}
        .token.selector, .token.attr-name, .token.string, .token.char, .token.builtin, .token.inserted {{ color: #68d391; }}
        .token.operator, .token.entity, .token.url, .language-css .token.string, .style .token.string {{ color: #4fd1c7; }}
        .token.atrule, .token.attr-value, .token.keyword {{ color: #9f7aea; }}
        .token.function, .token.class-name {{ color: #fbb6ce; }}
        .token.regex, .token.important, .token.variable {{ color: #f6ad55; }}

        /* --- 页脚 --- */
        .footer {{ text-align: center; padding: 40px; font-size: 0.9em; color: #9ca3af; }}
        
        /* --- 响应式 --- */
        @media (max-width: 1200px) {{
            .container {{ flex-direction: column; }}
            .sidebar {{ position: static; width: 100%; height: auto; border-right: none; border-bottom: 1px solid var(--border-color); }}
            main.content {{ padding: 40px 5%; }}
            .cursor-glow {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="cursor-glow"></div>
    <div class="container">
        <aside class="sidebar">
            <div class="sidebar-header"><h1>{sidebar_title}</h1></div>
            <nav class="toc">
                <h3>目录</h3>
                <ul>{toc_html}</ul>
            </nav>
        </aside>
        <main class="content">
            {cards_html}
            <footer class="footer">
                <p>🚀 由 AstrBot 插件 astrbot_plugin_deepresearch 生成</p>
                <p>📅 生成时间: {self._get_current_time()}</p>
                <p>该内容由网络搜索和 LLM 生成，请注意甄别内容的真实性！！！</p>
                <p>AstrBot 开发团队与 deepresearch 插件开发作者不对生成内容承担任何责任。</p>
            </footer>
        </main>
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function () {{
            const inViewObserver = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        entry.target.classList.add('in-view');
                    }}
                }});
            }}, {{ threshold: 0.2 }});
            document.querySelectorAll('.report-card').forEach(el => inViewObserver.observe(el));

            const tocLinks = document.querySelectorAll('.toc a');
            const sectionObserver = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    const id = entry.target.getAttribute('id');
                    const link = document.querySelector(`.toc a[href="#${{id}}"]`);
                    if (link) {{
                        if (entry.isIntersecting && entry.intersectionRatio > 0.5) {{
                            tocLinks.forEach(l => l.classList.remove('active'));
                            link.classList.add('active');
                        }} else {{
                            link.classList.remove('active');
                        }}
                    }}
                }});
            }}, {{ rootMargin: "-30% 0px -60% 0px", threshold: [0.5, 1.0] }});
            document.querySelectorAll('.report-card').forEach(section => sectionObserver.observe(section));

            document.querySelectorAll('.toc a').forEach(anchor => {{
                anchor.addEventListener('click', function (e) {{
                    e.preventDefault();
                    const targetId = this.getAttribute('href');
                    const targetElement = document.querySelector(targetId);
                    if (targetElement) {{
                        targetElement.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                        targetElement.classList.add('highlight');
                        setTimeout(() => {{
                            targetElement.classList.remove('highlight');
                        }}, 1500);
                    }}
                }});
            }});

            const glow = document.querySelector('.cursor-glow');
            if (glow && window.matchMedia('(pointer: fine)').matches) {{
                document.addEventListener('mousemove', (e) => {{
                    glow.style.transform = `translate(${{e.clientX}}px, ${{e.clientY}}px)`;
                }});
                 document.addEventListener('mouseleave', () => {{ glow.style.opacity = '0'; }});
                 document.addEventListener('mouseenter', () => {{ glow.style.opacity = '0.1'; }});
            }}
        }});
    </script>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
    <script>
        if (typeof Prism !== 'undefined') {{
            Prism.plugins.autoloader.languages_path = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/';
            Prism.highlightAll();
        }}
    </script>
</body>
</html>
"""

    def _save_to_temp_file(self, html_content: str) -> str:
        """保存HTML内容到临时文件"""
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(
            temp_dir, f"astrbot_svg_report_{self._get_timestamp()}.html"
        )
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        return temp_file

    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_timestamp(self) -> str:
        """获取时间戳"""
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
