# main.py
import asyncio
import json
import httpx
import re
import markdown
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any, AsyncGenerator, Union

# 导入 AstrBot API
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.provider import Provider, LLMResponse
import astrbot.api.message_components as Comp

# 导入新的模块架构
from .config import (
    DEFAULT_CONFIG,
    SUPPORTED_OUTPUT_FORMATS,
    DEFAULT_HEADERS,
    HTML_REPORT_TEMPLATE,
)
from .search_engine_lib.models import SearchQuery, SearchResponse, SearchResultItem
from .search_engine_lib.base import BaseSearchEngine
from .search_engine_lib import initialize, list_engines, get_engine
from .url_resolver import URLResolverManager
from .output_format import OutputFormatManager

from .core.constants import (
    PLUGIN_NAME,
    PLUGIN_VERSION,
    PLUGIN_DESCRIPTION,
    PLUGIN_AUTHOR,
    PLUGIN_REPO,
)

# 从配置中获取常量
MAX_CONTENT_LENGTH = DEFAULT_CONFIG["max_content_length"]
MAX_SELECTED_LINKS = DEFAULT_CONFIG["max_selected_links"]
FETCH_TIMEOUT = DEFAULT_CONFIG["fetch_timeout"]
HEADERS = DEFAULT_HEADERS


@register(
    PLUGIN_NAME,
    PLUGIN_AUTHOR,
    PLUGIN_DESCRIPTION,
    PLUGIN_VERSION,
    PLUGIN_REPO,
)
class DeepResearchPlugin(Star):
    """
    AstrBot 深度研究插件，实现查询处理、信息检索、内容处理、报告生成四个阶段。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        # 初始化异步 HTTP 客户端
        self.client = httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            http2=True,
            follow_redirects=True,
            verify=False,
            headers=HEADERS,
        )
        self.search_engine_initialized = False
        self.available_engine_names: List[str] = []
        self.max_count: int = self.config.get("max_search_results_per_term", 6)
        self.max_terms: int = self.config.get("max_terms_to_search", 3)
        engine_config = self.config.get("engine_config", {})

        # 初始化输出格式管理器
        output_config = {
            "default_format": self.config.get("default_output_format", "image")
        }
        self.output_manager = OutputFormatManager(output_config)

        asyncio.create_task(self.initialize_engine(engine_config))
        logger.info("DeepResearchPlugin 初始化完成，HTTP 客户端已创建。")

    async def initialize_engine(self, engine_config):
        try:
            logger.info("DeepResearchPlugin: 正在使用配置初始化 search_engine_lib...")
            await initialize(engine_config)
            # 获取所有初始化成功的引擎列表
            self.available_engine_names = list_engines()

            # 检查是否有至少一个引擎可用
            if not self.available_engine_names:
                logger.error(
                    "DeepResearchPlugin: search_engine_lib 初始化完成，但未找到任何可用/已配置的引擎！请检查 engine_config。"
                )
                self.search_engine_initialized = False
            else:
                self.search_engine_initialized = True
                logger.info(
                    f"DeepResearchPlugin: search_engine_lib 初始化成功。将使用所有可用引擎: {self.available_engine_names}"
                )
        except Exception as e:
            logger.error(
                f"DeepResearchPlugin: 初始化 search_engine_lib 失败: {e}", exc_info=True
            )
            self.search_engine_initialized = False
            self.available_engine_names = []  # 确保失败时列表为空

    async def terminate(self):
        """
        插件终止，清理资源
        """
        logger.info("DeepResearchPlugin 正在关闭 HTTP Client...")
        # 必须显式关闭长期存在的 client 实例
        if hasattr(self, "client") and self.client and not self.client.is_closed:
            try:
                await self.client.aclose()
                logger.info("DeepResearchPlugin HTTP Client 已关闭。")
            except Exception as e:
                logger.error(f"DeepResearchPlugin 关闭 HTTP Client 时出错: {e}")

    # ------------------ LLM 调用辅助函数 ------------------
    async def _call_llm(
        self,
        provider: Provider,
        prompt: str,
        system_prompt: str = "",
        max_retries: int = 3,
    ) -> Optional[str]:
        """封装 LLM 调用，带重试和速率限制，返回文本内容或 None"""
        for attempt in range(max_retries):
            try:
                # 调用 AstrBot 提供的 LLM 接口
                llm_response: LLMResponse = await provider.text_chat(
                    prompt=prompt,
                    session_id=None,
                    contexts=[],
                    image_urls=[],
                    func_tool=None,
                    system_prompt=system_prompt,
                )
                if (
                    llm_response
                    and llm_response.role == "assistant"
                    and llm_response.completion_text
                ):
                    # 尝试清理 JSON 字符串前后的 markdown 标记
                    content = llm_response.completion_text.strip()
                    content = re.sub(r"^```json\s*", "", content, flags=re.IGNORECASE)
                    content = re.sub(r"\s*```$", "", content, flags=re.IGNORECASE)
                    return content
                else:
                    logger.warning(f"LLM 调用未返回有效助手消息: {llm_response}")
                    return None

            except Exception as e:
                error_msg = str(e).lower()

                # 检查是否是速率限制错误
                if "rate" in error_msg or "429" in error_msg or "quota" in error_msg:
                    if attempt < max_retries - 1:
                        # 指数退避延迟
                        delay = (2**attempt) * 15  # 15秒, 30秒, 60秒
                        logger.warning(
                            f"LLM API速率限制，等待 {delay} 秒后重试 (尝试 {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"LLM API速率限制，已达到最大重试次数: {e}")
                        return None
                else:
                    logger.error(f"调用 LLM 发生错误: {e}", exc_info=True)
                    return None

        return None

    # ------------------ 阶段一：查询处理与扩展 (Query Processing) ------------------
    async def _stage1_query_processing(
        self, provider: Provider, query: str
    ) -> Optional[Dict[str, Any]]:
        """阶段一：使用 LLM 解析和扩展用户查询"""
        logger.info(f"阶段一：开始处理查询: {query}")
        system_prompt = """
        你是一个研究分析助手。你的任务是解析用户的原始问题，并将其分解和扩展，以便进行后续的信息检索。
        请严格按照以下 JSON 格式返回结果，不要包含任何额外的解释或文本。
        格式要求：
        {
            "original_question": "用户输入的原话",
            "sub_questions": ["将复杂问题拆解成的具体、易于检索的小问题列表"],
            "sub_topics": ["问题中包含的相关主题关键词列表"],
            "expansion_questions": ["基于原始问题，生成的有助于提供更全面答案的扩展性问题列表"],
            "search_queries": ["结合以上所有信息，生成 3-5 个用于搜索引擎的高质量搜索关键词短语列表"]
        }
        """
        response_text = await self._call_llm(provider, query, system_prompt)
        if not response_text:
            return None
        try:
            parsed_data = json.loads(response_text)
            # 将所有问题和搜索词合并，用于后续搜索
            all_search_terms = set()
            all_search_terms.add(query)
            all_search_terms.update(parsed_data.get("sub_questions", []))
            all_search_terms.update(parsed_data.get("sub_topics", []))
            all_search_terms.update(parsed_data.get("expansion_questions", []))
            all_search_terms.update(parsed_data.get("search_queries", []))
            parsed_data["all_search_terms"] = list(all_search_terms)
            logger.info(
                f"阶段一：查询解析成功。生成搜索词 {len(parsed_data['all_search_terms'])} 个。"
            )
            return parsed_data
        except json.JSONDecodeError:
            logger.error(f"阶段一：LLM 返回的 JSON 解析失败: {response_text[:200]}...")
            return None

    # ------------------ 阶段二：信息检索与筛选 (Information Retrieval & Filtering) ------------------
    # --- 新增: 单个搜索词查询辅助函数 ---
    async def _run_single_search(
        self, engine: BaseSearchEngine, term: str, count: int
    ) -> List[SearchResultItem]:
        """使用指定引擎和搜索词执行一次搜索，并处理异常"""
        if not term:
            return []
        logger.info(f"使用引擎 '{engine.name}' 搜索: '{term}' (count={count})")
        try:
            query_obj = SearchQuery(query=term, count=count)
            response: SearchResponse = await engine.search(query_obj)
            logger.debug(f"搜索 '{term}' 返回 {len(response.results)} 条结果。")
            return response.results
        except Exception as e:
            logger.error(
                f"使用引擎 '{engine.name}' 搜索 '{term}' 时发生错误: {e}", exc_info=True
            )
            return []

    # ----------------------------------
    async def _search_web(self, search_terms: List[str]) -> List[Dict[str, str]]:
        """
        阶段二：多源信息检索
        使用 search_engine_lib 中【所有可用引擎】并发搜索多个关键词，并合并、去重、格式化结果。
        """
        # 检查初始化状态和引擎列表
        if not self.search_engine_initialized or not self.available_engine_names:
            logger.error(
                "阶段二：search_engine_lib 未初始化、不可用，或没有找到任何可用引擎，无法执行搜索。"
            )
            return []

        if not search_terms:
            logger.warning("阶段二：没有提供搜索词。")
            return []
        # 获取所有可用的引擎实例
        engines: List[BaseSearchEngine] = []
        for name in self.available_engine_names:
            try:
                engine = get_engine(name)
                if engine:
                    engines.append(engine)
            except Exception as e:
                # 如果获取某个引擎失败，记录日志并跳过，继续使用其他引擎
                logger.warning(
                    f"阶段二：获取引擎 '{name}' 实例失败: {e}，将跳过此引擎。"
                )

        if not engines:
            logger.error("阶段二：无法获取任何有效的搜索引擎实例。")
            return []
        # 限制实际用于搜索的词条数量
        terms_to_search = [term for term in search_terms if term][: self.max_terms]

        engine_names_str = ", ".join([e.name for e in engines])
        logger.warning(
            f"阶段二：注意 API 消耗！准备使用 {len(engines)} 个引擎 ({engine_names_str}) 对 {len(terms_to_search)} 个词条进行并发搜索 (每个组合最多 {self.max_count} 条结果)..."
        )
        logger.info(
            f"阶段二：总计将执行最多 {len(engines) * len(terms_to_search)} 次搜索 API 调用。"
        )
        # 创建并行搜索任务列表: [engine1_term1, engine1_term2, ..., engine2_term1, engine2_term2, ...]
        tasks = []
        for engine in engines:  # 遍历每个引擎
            for term in terms_to_search:  # 遍历每个搜索词
                tasks.append(self._run_single_search(engine, term, self.max_count))

        # 并行执行
        all_results_nested: List[
            Union[List[SearchResultItem], Exception]
        ] = await asyncio.gather(*tasks, return_exceptions=True)
        # 展平结果列表，过滤掉异常，并转换格式 + 去重
        formatted_results: List[Dict[str, str]] = []
        seen_urls = set()
        total_items_found = 0

        for result_batch in all_results_nested:
            if isinstance(result_batch, list):
                total_items_found += len(result_batch)
                for item in result_batch:
                    url_str = str(item.link)
                    if url_str not in seen_urls:
                        formatted_results.append(
                            {
                                "title": item.title,
                                "url": url_str,
                                "snippet": item.snippet,
                            }
                        )
                        seen_urls.add(url_str)
            elif isinstance(result_batch, Exception):
                logger.warning(
                    f"一个搜索任务失败: {result_batch}"
                )  # 哪个引擎哪个词失败会在 _run_single_search 中记录

        logger.info(
            f"阶段二：所有搜索引擎共找到 {total_items_found} 条结果，合并去重后剩余 {len(formatted_results)} 条。"
        )
        return formatted_results

    async def _stage2_link_selection(
        self, provider: Provider, original_query: str, links: List[Dict[str, str]]
    ) -> List[str]:
        """阶段二：链接去重与 LLM 筛选"""
        # _search_web 已经去重过，这里可以简化或保留作为双重保险
        unique_links_dict = {link["url"]: link for link in links}
        unique_links = list(unique_links_dict.values())
        if not unique_links:
            return []
        logger.info(
            f"阶段二：准备从 {len(unique_links)} 个链接中进行 LLM 筛选，最多选择 {MAX_SELECTED_LINKS} 个..."
        )  # 更新日志
        link_descriptions = "\n".join(
            [
                f"- URL: {link['url']}\n  Title: {link['title']}\n  Snippet: {link.get('snippet', '')}"
                for link in unique_links
            ]
        )

        # 更新 prompt 中的 MAX_SELECTED_LINKS
        system_prompt = f"""
        你是一个研究分析助手。你的任务是从候选链接列表中，根据与原始问题的相关性，筛选出最相关、最有价值的最多 {MAX_SELECTED_LINKS} 个链接。
        原始问题： "{original_query}"

        请严格按照以下 JSON 列表格式返回结果，只包含选定链接的 URL 字符串，不要包含任何额外的解释或文本。
        格式要求：
        ["url1", "url2", "url3"]
        如果没有任何链接相关，返回空列表: []
        """
        prompt = f"请从以下链接中筛选出最相关的最多 {MAX_SELECTED_LINKS} 个：\n\n{link_descriptions}"
        response_text = await self._call_llm(provider, prompt, system_prompt)
        if not response_text:
            return []
        try:
            selected_urls = json.loads(response_text)
            if not isinstance(selected_urls, list):
                raise TypeError("LLM did not return a list")
            final_list = [
                str(url) for url in selected_urls if str(url) in unique_links_dict
            ][:MAX_SELECTED_LINKS]  # 使用更新后的 MAX_SELECTED_LINKS
            logger.info(f"阶段二：LLM 筛选完成，选定 {len(final_list)} 个链接。")
            return final_list
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(
                f"阶段二：LLM 链接筛选结果 JSON 解析失败 ({e}): {response_text[:200]}..."
            )
            return list(unique_links_dict.keys())[:MAX_SELECTED_LINKS]

    # ------------------ 阶段三：内容处理与分析 (Content Processing & Analysis) ------------------

    async def _resolve_baidu_redirect(self, url: str) -> Optional[str]:
        """解析百度重定向链接，获取真实URL"""
        try:
            # 直接访问百度重定向链接，让其自动跳转
            response = await self.client.get(url, follow_redirects=True)
            final_url = str(response.url)

            # 如果最终URL还是百度域名，可能是解析失败
            if "baidu.com" in final_url:
                logger.warning(f"百度重定向解析失败，仍为百度域名: {final_url}")
                return None

            logger.info(f"百度重定向解析成功: {url} -> {final_url}")
            return final_url

        except Exception as e:
            logger.warning(f"百度重定向解析失败: {url}, 错误: {e}")
            return None

    async def _fetch_and_parse_content(self, url: str) -> Optional[str]:
        """
        抓取单个 URL 的内容，解析并清理 HTML，转换为纯文本。
        使用长期存在的 self.client 实例。
        """
        logger.info(f"阶段三：正在抓取 URL: {url} ")

        # 检查是否是百度重定向链接并尝试解析
        if "baidu.com/link" in url:
            logger.info(f"检测到百度重定向链接，尝试解析: {url}")
            real_url = await self._resolve_baidu_redirect(url)
            if real_url:
                url = real_url  # 使用解析后的真实URL
                logger.info(f"使用解析后的真实URL: {url}")
            else:
                logger.info(f"百度重定向解析失败，跳过处理: {url}")
                return None

        html_content = ""
        try:
            # 修复：正确使用httpx客户端
            response = await self.client.get(url)
            response.raise_for_status()  # 触发 HTTPStatusError

            # 获取内容并限制大小
            content = response.content
            if len(content) > MAX_CONTENT_LENGTH * 3:
                logger.warning(f"URL {url} 内容过大，截断读取。")
                content = content[: MAX_CONTENT_LENGTH * 3]

            # 获取文本内容
            html_content = response.text
            # --- HTML 解析与清理 (保持原有逻辑) ---
            if not html_content:
                return None

            soup = BeautifulSoup(html_content, "lxml")
            # 移除 script 和 style
            for script in soup(
                ["script", "style", "noscript", "nav", "footer", "header", "aside"]
            ):
                script.decompose()

            # 优先尝试获取 article 标签
            main_content_tag = (
                soup.find("article") or soup.find("main") or soup.body or soup
            )

            # 转换为 markdown 再转回 text 以更好清理格式
            md_text = markdown.markdown(main_content_tag.decode_contents())
            text = "".join(BeautifulSoup(md_text, "lxml").findAll(string=True))
            # 清理多余空白和换行
            cleaned_text = re.sub(r"\s+", " ", text).strip()
            final_text = cleaned_text[:MAX_CONTENT_LENGTH]
            logger.debug(
                f"阶段三：URL {url} 内容抓取并清理完成，长度: {len(final_text)}"
            )
            return final_text
            # --- 结束 HTML 解析 ---
        # --- 修改: 捕获具体 httpx 异常 ---
        except httpx.TimeoutException as e:
            logger.warning(f"抓取 URL {url} 超时 ({FETCH_TIMEOUT}s): {e}")
            return None
        except httpx.HTTPStatusError as e:
            # 由 raise_for_status() 触发，如 404, 500
            logger.warning(
                f"抓取 URL {url} 发生 HTTP 错误: 状态码={e.response.status_code}, 错误={e}"
            )
            return None
        except httpx.RequestError as e:
            # 包括连接错误, DNS 错误等
            logger.warning(f"抓取 URL {url} 发生请求错误: {e}")
            return None
        # ------------------------------------
        except Exception as e:
            # 捕获 BeautifulSoup, markdown, re 等解析过程中的其他错误
            logger.error(
                f"抓取或解析 URL {url} 发生未知错误: {e}", exc_info=True
            )  # 保留 exc_info
            return None

    async def _summarize_content(
        self, provider: Provider, query: str, url: str, content: str
    ) -> Optional[str]:
        """使用 LLM 总结单个文档内容"""
        logger.info(f"阶段三：正在总结 URL {url} 的内容...")
        system_prompt = f"""
        你是一个研究分析助手。请基于以下提供的文本内容，总结出与原始查询：“{query}” 高度相关的关键信息。
        总结应清晰、简洁，突出要点。忽略广告、导航等无关内容。
        请直接返回总结文本，不要包含任何额外的解释、标题或问候语。
        """
        prompt = f"请根据查询 “{query}” 总结以下文本：\n\n---\n{content}\n---"
        summary = await self._call_llm(provider, prompt, system_prompt)
        if summary:
            logger.info(f"阶段三：URL {url} 总结完成。")
        else:
            logger.warning(f"阶段三：URL {url} 总结失败。")
        return summary

    async def _process_one_link(
        self, provider: Provider, query: str, url: str
    ) -> Optional[Dict[str, str]]:
        """处理单个链接：抓取 -> 总结"""
        content = await self._fetch_and_parse_content(url)
        if content and len(content) > 100:  # 忽略内容过少的页面
            summary = await self._summarize_content(provider, query, url, content)
            if summary:
                return {"url": url, "summary": summary}
        return None

    async def _stage3_content_processing(
        self, provider: Provider, query: str, selected_links: List[str]
    ) -> List[Dict[str, str]]:
        """阶段三：并行抓取内容并生成摘要"""
        logger.info("阶段三：开始并行抓取和总结内容...")
        # 创建并行任务
        tasks = [
            self._process_one_link(provider, query, link) for link in selected_links
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 过滤掉失败或无效的结果
        summaries = [
            res
            for res in results
            if isinstance(res, dict) and res is not None and "summary" in res
        ]
        logger.info(
            f"阶段三：成功处理并总结了 {len(summaries)} / {len(selected_links)} 个链接。"
        )
        return summaries

    async def _stage3_aggregation(
        self,
        provider: Provider,
        query: str,
        expansion_questions: List[str],
        summaries: List[Dict[str, str]],
    ) -> Optional[str]:
        """阶段三：LLM 聚合分析所有摘要，生成 Markdown 报告"""
        logger.info("阶段三：开始聚合分析所有摘要...")
        if not summaries:
            return "未能从任何来源获取有效摘要，无法生成报告。"
        # 准备 LLM 输入
        summaries_input = "\n\n".join(
            [f"### 来源: {item['url']}\n{item['summary']}\n---" for item in summaries]
        )
        expansion_q_str = (
            "\n".join([f"- {q}" for q in expansion_questions])
            if expansion_questions
            else "无"
        )
        system_prompt = f"""
        你是一个高级研究分析师。你的任务是综合来自多个来源的摘要信息，生成一份结构清晰、内容连贯、逻辑严密的深度研究报告（Markdown 格式）。

        原始查询: "{query}"

        需要额外考虑和回答的扩展问题:
        {expansion_q_str}
        报告要求：
        1. 格式：使用标准的 Markdown 语法。
        2. 结构：应包含标题、引言、主体段落（可以按主题或扩展问题分节）、结论。
        3. 内容：综合所有来源的信息，对比不同观点（如果存在），整合信息，构建逻辑。
        4. 引用：在引用了某个来源信息的句子或段落末尾，明确标注来源，格式为 ` [来源: URL]`。
        5. 目标：全面、深入地回答原始查询及扩展问题。
        6. 输出：直接输出 Markdown 报告正文，不要包含任何额外的解释或问候语。
        """
        prompt = f"请根据以下来自不同来源的摘要信息，生成一份关于 “{query}” 的深度研究报告：\n\n{summaries_input}"
        report_markdown = await self._call_llm(provider, prompt, system_prompt)
        if report_markdown:
            logger.info("阶段三：聚合分析完成，Markdown 报告已生成。")
        else:
            logger.warning("阶段三：聚合分析失败。")
        return report_markdown

    # ------------------ 阶段四：报告生成与交付 (Report Generation & Delivery) ------------------
    async def _stage4_report_generation(
        self, markdown_text: str, output_format: str = None
    ) -> Optional[Any]:
        """阶段四：使用输出格式管理器生成报告"""
        if not output_format:
            output_format = self.output_manager.get_default_format()

        logger.info(f"阶段四：开始生成 {output_format} 格式报告...")

        try:
            # 使用输出格式管理器格式化报告
            result = await self.output_manager.format_report(
                markdown_content=markdown_text,
                format_name=output_format,
                star_instance=self,  # 传递Star实例用于图片渲染
            )

            if result:
                logger.info(f"阶段四：{output_format} 格式报告生成成功。")
            else:
                logger.warning(f"阶段四：{output_format} 格式报告生成失败。")

            return result
        except Exception as e:
            logger.error(
                f"阶段四：生成 {output_format} 格式报告失败: {e}", exc_info=True
            )
            return None

    # ------------------ 主流程控制 ------------------

    async def _run_research_pipeline(
        self, event: AstrMessageEvent, query: str, output_format: str = None
    ) -> AsyncGenerator[MessageEventResult, None]:
        """执行完整的研究流程管线，使用异步生成器发送中间状态和最终结果"""
        # 检查 LLM
        provider = self.context.get_using_provider()
        if not provider:
            yield event.plain_result(
                "❌ 错误：未配置或启用大语言模型(LLM)，无法执行研究。"
            )
            return

        start_time = asyncio.get_running_loop().time()
        yield event.plain_result(
            f"🔎 收到研究请求: '{query}'\n⏳ 开始阶段一：查询处理与扩展..."
        )

        try:
            # 阶段一
            parsed_query = await self._stage1_query_processing(provider, query)
            if not parsed_query or not parsed_query.get("all_search_terms"):
                yield event.plain_result("❌ 阶段一失败：LLM未能有效解析查询。")
                return
            yield event.plain_result(
                "✅ 阶段一完成。\n⏳ 开始阶段二：信息检索与筛选..."
            )
            # 阶段二
            search_terms = parsed_query.get("search_queries", []) or parsed_query.get(
                "all_search_terms", []
            )
            initial_links = await self._search_web(search_terms)
            if not initial_links:
                yield event.plain_result(
                    "⚠️ 阶段二警告：网络搜索未返回任何初始结果（或搜索功能未实现）。"
                )
                # 如果搜索失败，尝试直接让LLM回答
                yield event.plain_result("⚠️ 尝试让LLM根据自身知识直接生成报告...")
                direct_summary = await self._summarize_content(
                    provider,
                    query,
                    "LLM Knowledge Base",
                    "请基于你自身的知识库，生成一份关于此主题的报告。",
                )
                if direct_summary:
                    summaries = [
                        {"url": "LLM Knowledge Base", "summary": direct_summary}
                    ]
                    selected_links = ["LLM Knowledge Base"]
                else:
                    yield event.plain_result(
                        "❌ 阶段二失败：搜索和LLM自身知识均无法提供信息。"
                    )
                    return
            else:
                yield event.plain_result(
                    f"ℹ️ 搜索到 {len(initial_links)} 个初始链接，开始筛选..."
                )
                selected_links = await self._stage2_link_selection(
                    provider, query, initial_links
                )
                if not selected_links:
                    yield event.plain_result(
                        "❌ 阶段二失败：LLM未能从结果中筛选出相关链接。"
                    )
                    return
                yield event.plain_result(
                    f"✅ 阶段二完成。筛选出 {len(selected_links)} 个链接。\n⏳ 开始阶段三：内容处理与分析..."
                )
                # 阶段三 - 处理
                summaries = await self._stage3_content_processing(
                    provider, query, selected_links
                )
                if not summaries:
                    yield event.plain_result(
                        "❌ 阶段三失败：未能从任何选定链接抓取或总结有效内容。"
                    )
                    return
                yield event.plain_result(
                    f"ℹ️ 已抓取并总结 {len(summaries)} 篇内容。开始聚合分析..."
                )

            # 阶段三 - 聚合
            aggregated_markdown = await self._stage3_aggregation(
                provider, query, parsed_query.get("expansion_questions", []), summaries
            )
            if not aggregated_markdown:
                yield event.plain_result("❌ 阶段三失败：LLM内容聚合分析失败。")
                return
            yield event.plain_result(
                "✅ 阶段三完成。\n⏳ 开始阶段四：报告生成与渲染..."
            )
            # 阶段四
            report_result = await self._stage4_report_generation(
                aggregated_markdown, output_format
            )

            end_time = asyncio.get_running_loop().time()
            duration = round(end_time - start_time, 2)

            # 获取实际使用的输出格式
            actual_format = output_format or self.output_manager.get_default_format()

            # 最终输出
            status_msg = f"✅ 深度研究完成！总耗时: {duration} 秒。"

            if report_result:
                if actual_format == "image":
                    # 图片格式：使用消息链发送文本和图片
                    yield event.chain_result(
                        [
                            Comp.Plain(text=status_msg + "\n为您生成了图片报告："),
                            Comp.Image.fromURL(report_result),
                        ]
                    )
                elif actual_format == "html":
                    # HTML格式：使用File组件发送HTML文件
                    import os

                    filename = os.path.basename(report_result)
                    yield event.chain_result(
                        [
                            Comp.Plain(
                                text=status_msg + "\n为您生成了HTML报告："
                            ),
                            Comp.File(name=filename, file=report_result),
                        ]
                    )
                else:
                    # 其他格式：直接返回结果
                    yield event.plain_result(
                        status_msg
                        + f"\n为您生成了{actual_format}格式报告：\n\n{report_result}"
                    )
            else:
                # 报告生成失败，回退到原始Markdown
                yield event.plain_result(
                    status_msg
                    + f"\n⚠️ {actual_format}格式报告生成失败，以下为原始 Markdown 报告：\n---\n"
                    + aggregated_markdown
                )
        except asyncio.TimeoutError:
            yield event.plain_result("❌ 研究过程超时。")
            logger.error("Pipeline Timeout", exc_info=True)
        except Exception as e:
            yield event.plain_result(
                f"❌ 研究过程中发生未知错误: {type(e).__name__} - {e}"
            )
            logger.error(f"Pipeline error for query '{query}': {e}", exc_info=True)

    @filter.command("deepresearch", alias={"研究", "深度研究"})
    async def handle_research_command(
        self, event: AstrMessageEvent, query: str = "", output_format: str = "image"
    ):
        """
        指令: /deepresearch <查询内容> [输出格式]
        对指定内容进行多阶段深度研究并生成报告。
        """
        if not query:
            available_formats = self.output_manager.get_available_formats()
            formats_text = "\n".join(
                [
                    f"  - {fmt['name']}: {fmt['description']}"
                    for fmt in available_formats
                ]
            )

            yield event.plain_result(
                f"请输入要研究的内容。\n\n"
                f"用法: /deepresearch <查询内容> [输出格式]\n\n"
                f"支持的输出格式:\n{formats_text}\n\n"
                f"示例:\n"
                f"  /deepresearch 人工智能的未来发展趋势\n"
                f"  /deepresearch Python编程 markdown\n"
                f"  /deepresearch 区块链技术 html"
            )
            return

        # 验证输出格式是否支持
        if not self.output_manager.is_format_supported(output_format):
            available_formats = [
                fmt["name"] for fmt in self.output_manager.get_available_formats()
            ]
            yield event.plain_result(
                f"❌ 不支持的输出格式: '{output_format}'\n"
                f"支持的格式: {', '.join(available_formats)}"
            )
            return

        logger.info(f"用户指定输出格式: {output_format}")

        # 使用异步生成器模式，逐个 yield 消息
        async for message_result in self._run_research_pipeline(
            event, query, output_format
        ):
            yield message_result
        event.stop_event()  # 停止事件传播，防止LLM再次默认回复
