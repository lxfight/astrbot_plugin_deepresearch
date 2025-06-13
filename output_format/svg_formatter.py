# output_format/svg_formatter.py
"""SVG格式化器实现"""

import os
import re
import tempfile
import datetime
import html
from typing import Any, Dict, Optional, List, TypedDict

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
        return "svg"

    @property
    def description(self) -> str:
        return "生成精美的HTML报告文件"

    @property
    def file_extension(self) -> str:
        return ".html"

    async def format_report(
        self, markdown_content: str, star_instance: Star = None
    ) -> Optional[str]:
        if not self.validate_content(markdown_content):
            logger.warning("[SVGFormatter] Markdown内容为空")
            return None
        try:
            sections = self._parse_markdown_to_sections(markdown_content)
            html_content = self._generate_html_report(sections)
            temp_file = self._save_to_temp_file(html_content)
            logger.info("[SVGFormatter] HTML报告生成成功")
            return temp_file
        except Exception as e:
            logger.error(f"[SVGFormatter] 生成HTML报告时发生错误: {e}", exc_info=True)
            return None

    def _slugify(self, text: str) -> str:
        """生成URL友好的ID"""
        s = text.strip().lower()
        s = re.sub(r"[\s\(\)（）]+", "-", s)
        s = re.sub(r"[^\w\-_]", "", s)
        return s if s else "section"

    def _render_markdown(self, raw_text: str) -> str:
        """
        增强的Markdown渲染函数，支持代码块、多级标题和来源链接
        """
        import uuid

        # 用于存储占位符
        placeholders = {}

        # 1. 先处理代码块（在HTML转义之前处理）
        def code_block_replacer(match):
            language = match.group(1) if match.group(1) else "text"
            code_content = match.group(2)
            # 对代码内容进行HTML转义
            escaped_code = html.escape(code_content)
            
            # 语言名称映射和标准化
            language_map = {
                'py': 'python', 'js': 'javascript', 'ts': 'typescript',
                'sh': 'bash', 'shell': 'bash', 'yml': 'yaml',
                'json': 'json', 'xml': 'xml', 'html': 'markup',
                'css': 'css', 'scss': 'scss', 'sql': 'sql',
                'java': 'java', 'cpp': 'cpp', 'c': 'c',
                'go': 'go', 'rust': 'rust', 'php': 'php'
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

        # 2. 提取来源链接（在HTML转义之前）
        original_links = re.findall(r"\[来源:\s+(https?://[^\]]+)\]", text)
        original_link_iter = iter(original_links)

        def link_replacer(match):
            try:
                url = next(original_link_iter)
            except StopIteration:
                url = match.group(1)
            link_html = (
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">来源</a>'
            )
            placeholder = f"LINKPLACEHOLDER{uuid.uuid4().hex}ENDLINK"
            placeholders[placeholder] = link_html
            return placeholder

        text = re.sub(r"\[来源:\s+(https?://[^\]]+)\]", link_replacer, text)

        # 3. HTML转义（保护占位符）
        escaped_text = html.escape(text)

        # 4. 按段落分割处理
        paragraphs = escaped_text.split("\n\n")
        html_paragraphs = []

        for para in paragraphs:
            if not para.strip():
                continue

            # 检查是否是占位符（代码块或链接）
            if any(placeholder in para for placeholder in placeholders.keys()):
                # 直接添加，稍后会还原占位符
                html_paragraphs.append(para)
                continue

            # 按行处理段落内的Markdown
            lines = para.split("\n")
            processed_lines = []
            in_list = False

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # 处理标题（支持1-6级）
                if line.startswith("######"):
                    processed_lines.append(f"<h6>{line[7:].strip()}</h6>")
                    continue
                elif line.startswith("#####"):
                    processed_lines.append(f"<h5>{line[6:].strip()}</h5>")
                    continue
                elif line.startswith("####"):
                    processed_lines.append(f"<h4>{line[5:].strip()}</h4>")
                    continue
                elif line.startswith("###"):
                    processed_lines.append(f"<h3>{line[4:].strip()}</h3>")
                    continue
                elif line.startswith("##"):
                    processed_lines.append(f"<h2>{line[3:].strip()}</h2>")
                    continue
                elif line.startswith("#"):
                    processed_lines.append(f"<h1>{line[2:].strip()}</h1>")
                    continue

                # 处理列表
                is_list_item = line.startswith(("-", "*", "+"))
                if is_list_item and not in_list:
                    processed_lines.append("<ul>")
                    in_list = True
                if not is_list_item and in_list:
                    processed_lines.append("</ul>")
                    in_list = False

                if is_list_item:
                    # 移除列表标记
                    item_content = re.sub(r"^[-*+]\s*", "", line)
                    processed_lines.append(f"<li>{item_content}</li>")
                else:
                    processed_lines.append(line)

            if in_list:  # 关闭未闭合的列表
                processed_lines.append("</ul>")

            # 合并处理后的行
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

            # 包装成段落（除非已经是标题或列表）
            if not re.match(r"^\s*<(h[1-6]|ul|li)", para_content):
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
        final_html = re.sub(r"<br>\s*<(ul|/ul|li|h[1-6]|pre)", r"<\1", final_html)

        # 还原所有占位符
        for placeholder, content in placeholders.items():
            final_html = final_html.replace(placeholder, content)

        return final_html

    def _parse_markdown_to_sections(
        self, markdown_content: str
    ) -> List[MarkdownSection]:
        """将Markdown解析成章节"""
        sections: List[MarkdownSection] = []

        # 决定主分隔符
        has_h2 = bool(re.search(r"^##\s+", markdown_content, re.MULTILINE))
        primary_delimiter = "##" if has_h2 else "###"

        # 使用主分隔符来分割整个文档
        split_marker = "__SECTION_SPLIT__"
        content_with_markers = re.sub(
            f"^{primary_delimiter}\\s+",
            f"{split_marker}{primary_delimiter} ",
            markdown_content,
            flags=re.MULTILINE,
        )

        raw_sections = content_with_markers.split(split_marker)

        # 第一个块是引言（在第一个分隔符之前的内容）
        intro_content = raw_sections.pop(0).strip()
        if intro_content:
            # 分离标题和内容
            lines = intro_content.split("\n", 1)
            if lines[0].startswith("#"):
                # 有主标题的情况
                main_title = lines[0].replace("#", "").strip()
                intro_text = lines[1].strip() if len(lines) > 1 else ""
                # 将主标题和引言内容合并
                full_intro = f"# {main_title}\n\n{intro_text}"
            else:
                full_intro = intro_content

            content_html = self._render_markdown(full_intro)
            sections.append(
                MarkdownSection(
                    id="introduction",  # 使用固定ID避免重复
                    title="报告概述",
                    level=1,
                    content_html=content_html,
                )
            )

        # 用于确保ID唯一性
        used_ids = set()
        section_counter = {}

        for raw_section in raw_sections:
            if not raw_section.strip():
                continue

            # 提取标题和内容
            lines = raw_section.strip().split("\n", 1)
            title = lines[0].replace(primary_delimiter, "").strip()
            content_md = lines[1] if len(lines) > 1 else ""

            content_html = self._render_markdown(content_md)

            # 生成唯一ID
            base_id = self._slugify(title)
            if base_id in used_ids:
                section_counter[base_id] = section_counter.get(base_id, 1) + 1
                unique_id = f"{base_id}-{section_counter[base_id]}"
            else:
                unique_id = base_id
            used_ids.add(unique_id)

            sections.append(
                MarkdownSection(
                    id=unique_id,
                    title=title,
                    level=2,
                    content_html=content_html,
                )
            )

        return sections

    def _generate_html_report(self, sections: List[MarkdownSection]) -> str:
        """生成完整的HTML报告 (注入了丰富的动画特效)"""
        # 为目录项添加动画延迟
        toc_html = "".join(
            f'<li style="--anim-delay: {i * 0.05}s;"><a href="#{s["id"]}">{s["title"]}</a></li>'
            for i, s in enumerate(sections)
        )
        
        # 提取主标题作为侧边栏标题
        sidebar_title = "AI研究报告"
        if sections and sections[0]["content_html"]:
            # 从第一个章节的HTML中提取h1标题
            import re
            h1_match = re.search(r'<h1>(.*?)</h1>', sections[0]["content_html"])
            if h1_match:
                # 清理HTML标签并提取纯文本
                clean_title = re.sub(r'<[^>]+>', '', h1_match.group(1))
                if clean_title and len(clean_title.strip()) > 0:
                    sidebar_title = clean_title.strip() + " - 研究报告"

        cards_html = ""
        for section in sections:
            section_id = section["id"]
            # 为标题的每个字符包裹<span>，用于动画
            title_spans = "".join(
                f'<span class="char" style="--char-delay: {i * 0.03}s;">{char}</span>'
                for i, char in enumerate(section["title"])
            )
            section_title_html = f'<h2 class="card-title" data-title="{section["title"]}">{title_spans}</h2>'

            section_content = section["content_html"]

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
    <title>AI深度研究报告 - 动态版</title>
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
            margin-top: 2.2em; margin-bottom: 1em; font-weight: 600; line-height: 1.4; color: var(--text-primary);
        }}
        .card-content h1 {{ font-size: 1.5em; }}
        .card-content h2 {{ font-size: 1.35em; border-bottom: 1px solid #f3f4f6; padding-bottom: 0.4em; }}
        .card-content h3 {{ font-size: 1.2em; }}
        .card-content h4 {{ font-size: 1.1em; color: #374151; }}
        .card-content h5 {{ font-size: 1.05em; color: #4b5563; }}
        .card-content h6 {{ font-size: 1em; color: #6b7280; }}
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
        .card-content li {{
            position: relative; padding-left: 24px; margin-bottom: 0.75em; color: var(--text-secondary);
        }}
        .card-content li::before {{
            content: ''; position: absolute; left: 4px; top: 10px; width: 6px; height: 6px;
            background-color: var(--accent-color); border-radius: 50%;
        }}
        .card-content code {{
            font-family: 'SF Mono', 'Menlo', monospace; background-color: #f3f4f6;
            padding: 0.2em 0.5em; border-radius: 6px; font-size: 0.9em;
            color: #be123c; border: 1px solid var(--border-color);
        }}
        /* --- 代码高亮增强样式 --- */
        .card-content pre {{
            background-color: #2d3748; border-radius: 12px; padding: 1.5em;
            margin: 1.5em 0; overflow-x: auto; border: 1px solid #4a5568;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            position: relative;
        }}
        .card-content pre code {{
            background-color: transparent; padding: 0; border: none;
            color: #e2e8f0; font-size: 0.9em; line-height: 1.6;
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
        }}
        
        /* 代码块语言标识 */
        .card-content pre::before {{
            content: attr(data-language);
            position: absolute;
            top: 0.5em;
            right: 1em;
            color: #a0aec0;
            font-size: 0.75em;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        
        /* Prism.js主题自定义覆盖 */
        pre[class*="language-"] {{
            background: #2d3748 !important;
            border: 1px solid #4a5568 !important;
        }}
        
        /* 语法高亮颜色 */
        .token.comment,
        .token.prolog,
        .token.doctype,
        .token.cdata {{ color: #718096; }}
        
        .token.punctuation {{ color: #e2e8f0; }}
        
        .token.property,
        .token.tag,
        .token.boolean,
        .token.number,
        .token.constant,
        .token.symbol,
        .token.deleted {{ color: #f56565; }}
        
        .token.selector,
        .token.attr-name,
        .token.string,
        .token.char,
        .token.builtin,
        .token.inserted {{ color: #68d391; }}
        
        .token.operator,
        .token.entity,
        .token.url,
        .language-css .token.string,
        .style .token.string {{ color: #4fd1c7; }}
        
        .token.atrule,
        .token.attr-value,
        .token.keyword {{ color: #9f7aea; }}
        
        .token.function,
        .token.class-name {{ color: #fbb6ce; }}
        
        .token.regex,
        .token.important,
        .token.variable {{ color: #f6ad55; }}

        /* --- 页脚 --- */
        .footer {{ text-align: center; padding: 40px; font-size: 0.9em; color: #9ca3af; }}
        
        /* --- 响应式 --- */
        @media (max-width: 1200px) {{
            .container {{ flex-direction: column; }}
            .sidebar {{ position: static; width: 100%; height: auto; border-right: none; border-bottom: 1px solid var(--border-color); }}
            main.content {{ padding: 40px 5%; }}
            .cursor-glow {{ display: none; }} /* 移动端禁用光标 */
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
            </footer>
        </main>
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function () {{
            // --- 1. 元素入场动画观察器 ---
            const inViewObserver = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        entry.target.classList.add('in-view');
                    }}
                }});
            }}, {{ threshold: 0.2 }}); // 元素进入视口20%时触发
            document.querySelectorAll('.report-card').forEach(el => inViewObserver.observe(el));
            
            // --- 2. 目录高亮观察器 ---
            const tocLinks = document.querySelectorAll('.toc a');
            const sectionObserver = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    const id = entry.target.getAttribute('id');
                    const link = document.querySelector(`.toc a[href="#${{id}}"]`);
                    if (link) {{
                        if (entry.isIntersecting) {{
                            link.classList.add('active');
                        }} else {{
                            link.classList.remove('active');
                        }}
                    }}
                }});
            }}, {{ rootMargin: "-40% 0px -60% 0px" }}); // 调整触发区域
            document.querySelectorAll('.report-card').forEach(section => sectionObserver.observe(section));

            // --- 3. 目录点击跳转与高亮动画 ---
            document.querySelectorAll('.toc a').forEach(anchor => {{
                anchor.addEventListener('click', function (e) {{
                    e.preventDefault();
                    const targetId = this.getAttribute('href');
                    const targetElement = document.querySelector(targetId);
                    if (targetElement) {{
                        // 平滑滚动
                        targetElement.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                        
                        // 添加高亮动画
                        targetElement.classList.add('highlight');
                        setTimeout(() => {{
                            targetElement.classList.remove('highlight');
                        }}, 1500); // 动画持续时间
                    }}
                }});
            }});

            // --- 4. 卡片悬停高亮特效 (已移除3D倾斜) ---
            // 卡片悬停效果现在通过CSS处理，无需JavaScript

            // --- 5. 鼠标光标追随特效 ---
            const glow = document.querySelector('.cursor-glow');
            if (glow) {{
                document.addEventListener('mousemove', (e) => {{
                    glow.style.transform = `translate(${{e.clientX}}px, ${{e.clientY}}px)`;
                }});
                 document.addEventListener('mouseleave', () => {{
                    glow.style.opacity = '0';
                }});
                 document.addEventListener('mouseenter', () => {{
                    glow.style.opacity = '0.1';
                }});
            }}
        }});
    </script>
    
    <!-- Prism.js 核心和语言支持 -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
    <script>
        // 配置Prism.js自动加载器
        if (typeof Prism !== 'undefined') {{
            Prism.plugins.autoloader.languages_path = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/';
            
            // 手动高亮所有代码块
            document.addEventListener('DOMContentLoaded', function() {{
                Prism.highlightAll();
            }});
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
