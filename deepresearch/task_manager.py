import asyncio
import uuid
from typing import Dict, Optional, List, Any
from datetime import datetime

from astrbot.api import star, logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import Plain, Image

# 导入所有需要协调的模块
from .data_models import (
    UserResearchQuery,
    QueryAnalysisResult,
    RetrievedItem,
    RetrievalPhaseOutput,
    ProcessedContent,
    SourceInsight,
    SubTopicSynthesis,
    ReportSection,
    ResearchReport,
    DeepResearchTask,
)
from .llm_modules.query_parser import QueryParser
from .llm_modules.content_selector import ContentSelector
from .llm_modules.document_processor import DocumentProcessor
from .llm_modules.report_generator import ReportGenerator
from .retrieval.retriever_factory import RetrieverFactory

# from deepresearch.retrieval.custom_db_adapter import CustomDBAdapter # 如果有的话
from .content_processing.html_extractor import HTMLExtractor
from .output_formatter.report_formatter import (
    ReportFormatter,
)  # 包含md转html和html渲染图片
from .output_formatter.file_manager import FileManager


class TaskManager:
    """
    深度研究任务管理器，负责任务的启动、状态管理、进度通知和清理。
    它是 DeepResearch 插件的核心编排器。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        self.context = context
        self.config = config
        self.logger = logger
        self.active_tasks: Dict[str, DeepResearchTask] = {}  # 存储所有活跃任务
        self.task_futures: Dict[
            str, asyncio.Task
        ] = {}  # 存储任务对应的 asyncio.Task 对象

        # 初始化各个业务模块实例
        self.query_parser = QueryParser(context, config)
        self.content_selector = ContentSelector(context, config)
        self.document_processor = DocumentProcessor(context, config)
        self.report_generator = ReportGenerator(context, config)

        self.retriever_factory = RetrieverFactory(context, config)

        self.html_extractor = HTMLExtractor(context, config)
        self.report_formatter = ReportFormatter(context, config)
        self.file_manager = FileManager(context, config)

        self.logger.info("TaskManager 初始化完成，所有子模块已载入。")

    async def start_research_task(
        self, user_query: UserResearchQuery, event: AstrMessageEvent
    ) -> str:
        """
        启动一个新的深度研究任务。
        """
        task_id = str(uuid.uuid4())
        task = DeepResearchTask(task_id=task_id, user_query=user_query)
        self.active_tasks[task_id] = task

        # 将研究流程作为独立的 asyncio 任务运行，避免阻塞主线程
        task_coro = self._run_research_pipeline(task, event)
        task_future = asyncio.create_task(task_coro)
        self.task_futures[task_id] = task_future

        self.logger.info(f"深度研究任务 {task_id} 已启动。")
        return task_id

    async def _run_research_pipeline(
        self, task: DeepResearchTask, event: AstrMessageEvent
    ):
        """
        执行完整的深度研究流程。
        这是一个长运行的协程，会在后台执行所有步骤。
        """
        try:
            # 阶段1: LLM解析用户问题
            task.update_status("analyzing_query")
            await event.send(
                f"🤖 任务 `{task.task_id[:8]}` 启动：正在解析您的研究问题..."
            )
            query_analysis_result = await self.query_parser.parse_query(task.user_query)
            task.query_analysis_result = query_analysis_result
            await event.send(
                f"✅ 任务 `{task.task_id[:8]}`：问题解析完成。识别出 {len(query_analysis_result.identified_sub_topics)} 个子主题。"
            )

            # 阶段2: 多源信息检索 - 使用工厂模式
            task.update_status("retrieving_sources")
            await event.send(
                f"🔍 任务 `{task.task_id[:8]}`：正在从多源（网络、新闻、学术等）检索信息..."
            )
            all_retrieved_items: List[RetrievedItem] = []

            # 获取所有可用的检索器
            available_retrievers = self.retriever_factory.get_available_retrievers()
            self.logger.info(f"可用检索器类型：{list(available_retrievers.keys())}")

            # 从配置中提取搜索配置
            search_config = self._extract_complete_search_config()

            for (
                source_type,
                queries,
            ) in query_analysis_result.planned_search_queries.items():
                if not queries:
                    continue  # 没有为该来源生成查询词

                retriever = available_retrievers.get(source_type)
                if retriever:
                    self.logger.info(
                        f"使用检索器 '{retriever.__class__.__name__}' 进行 '{source_type}' 搜索。"
                    )
                    for query in queries:
                        self.logger.debug(f"执行 '{source_type}' 搜索: '{query}'")
                        try:
                            results = await retriever.search(query, search_config)
                            # 确保结果符合RetrievedItem模型
                            for result in results:
                                if not hasattr(result, "source") or not result.source:
                                    result.source = source_type
                                if not hasattr(result, "metadata"):
                                    result.metadata = {}
                                # 添加查询信息到元数据
                                result.metadata["original_query"] = query
                                result.metadata["retriever_type"] = (
                                    retriever.__class__.__name__
                                )

                            all_retrieved_items.extend(results)
                        except Exception as e:
                            self.logger.error(
                                f"搜索'{query}'时出错: {e}", exc_info=True
                            )
                else:
                    self.logger.warning(
                        f"检索器类型 '{source_type}' 未配置或不可用，跳过该来源的搜索。"
                    )

            retrieval_output = RetrievalPhaseOutput(
                query_analysis=query_analysis_result,
                all_retrieved_items=all_retrieved_items,
            )
            retrieval_output.perform_deduplication()  # URL去重
            task.retrieval_output = retrieval_output
            await event.send(
                f"✨ 任务 `{task.task_id[:8]}`：信息检索完成，共发现 {len(retrieval_output.unique_retrieved_items)} 条不重复的潜在相关链接。"
            )

            # 阶段3: LLM筛选与内容提取
            task.update_status("processing_content")
            await event.send(
                f"📄 任务 `{task.task_id[:8]}`：正在筛选相关内容并提取文本..."
            )
            processed_contents: List[ProcessedContent] = []
            relevant_contents: List[ProcessedContent] = []

            # 优化：并行抓取
            fetch_tasks = [
                self.html_extractor.extract_text(item.url)
                for item in retrieval_output.unique_retrieved_items
            ]
            extracted_texts = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for i, item in enumerate(retrieval_output.unique_retrieved_items):
                extracted_text = extracted_texts[i]
                if isinstance(extracted_text, Exception):
                    self.logger.warning(
                        f"抓取或提取 '{item.url}' 失败: {extracted_text}"
                    )
                    processed_item = ProcessedContent(
                        retrieved_item=item,
                        processing_error=str(extracted_text),
                        fetch_time=datetime.now(),
                    )
                else:
                    processed_item = ProcessedContent(
                        retrieved_item=item,
                        extracted_text=extracted_text,
                        fetch_time=datetime.now(),
                    )
                processed_contents.append(processed_item)

                # 仅对成功提取到文本的项进行相关性筛选
                if processed_item.extracted_text:
                    is_relevant, score = await self.content_selector.check_relevance(
                        query_analysis_result, item, processed_item.extracted_text
                    )
                    processed_item.is_relevant = is_relevant
                    processed_item.relevance_score = score
                    if is_relevant:
                        relevant_contents.append(processed_item)
                else:
                    processed_item.is_relevant = False  # 无法提取内容默认不相关

            task.processed_contents = processed_contents
            task.relevant_contents = relevant_contents
            await event.send(
                f"📝 任务 `{task.task_id[:8]}`：内容筛选与提取完成，获得 {len(relevant_contents)} 篇相关文档。"
            )

            # 阶段4: LLM文档处理与内容总结
            task.update_status("synthesizing_insights")
            await event.send(
                f"💡 任务 `{task.task_id[:8]}`：正在对文档进行深度分析与总结..."
            )

            # 并行处理每个相关文档的洞察提取
            insight_tasks = []
            for doc in relevant_contents:
                insight_tasks.append(
                    self.document_processor.process_and_summarize_document(
                        query_analysis_result, doc
                    )
                )

            # 展平列表的列表
            list_of_lists_of_insights = await asyncio.gather(*insight_tasks)
            source_insights: List[SourceInsight] = [
                insight for sublist in list_of_lists_of_insights for insight in sublist
            ]
            task.source_insights = source_insights

            # 按子主题聚合和综合
            sub_topic_syntheses: List[
                SubTopicSynthesis
            ] = await self.document_processor.synthesize_by_sub_topic(
                query_analysis_result, source_insights
            )
            task.sub_topic_syntheses = sub_topic_syntheses
            await event.send(
                f"📊 任务 `{task.task_id[:8]}`：文档分析与子主题总结完成。"
            )

            # 阶段5: LLM聚合分析与报告生成
            task.update_status("generating_report")
            await event.send(f"✍️ 任务 `{task.task_id[:8]}`：正在生成最终研究报告...")
            final_report = await self.report_generator.generate_full_report(
                task.user_query, query_analysis_result, sub_topic_syntheses
            )
            task.final_report = final_report
            await event.send(f"🎉 任务 `{task.task_id[:8]}`：研究报告已成功生成！")

            # 阶段6: 输出格式化与交付
            task.update_status("completed")
            await event.send(
                f"完成！任务 `{task.task_id[:8]}` 的报告标题为：`{final_report.main_title}`。"
            )

            # 默认输出格式
            default_format = self.config.get("output_config", {}).get(
                "default_output_format", "md"
            )
            await self._send_report_output(
                event, final_report, task.task_id, default_format
            )

        except Exception as e:
            error_message = f"研究任务 `{task.task_id[:8]}` 执行失败: {e}"
            self.logger.error(error_message, exc_info=True)
            task.update_status("failed", str(e))
            await event.send(f"😭 {error_message}")
        finally:
            # 清理任务，但保持 active_tasks 中的记录，直到用户主动清理或过期
            # self.cleanup_task(task.task_id) # 考虑是否在完成后立即清理future，但保留数据
            pass  # 暂时不立即清理，让用户可以查询状态和结果

    async def _send_report_output(
        self,
        event: AstrMessageEvent,
        report: ResearchReport,
        task_id: str,
        format_type: str,
    ):
        """根据指定格式发送报告输出。"""
        try:
            if format_type.lower() == "md":
                md_content = report.get_full_markdown_content()
                # 考虑报告过长时保存为文件并提供链接
                if len(md_content) > 2000:  # 假设消息最大长度
                    file_info = await self.file_manager.save_text_as_file(
                        md_content, f"deep_research_report_{task_id[:8]}.md", "md"
                    )
                    await event.send(
                        f"📄 报告Markdown文件已生成：{file_info['file_url']}"
                    )
                else:
                    await event.send(f"```markdown\n{md_content}\n```")
            elif format_type.lower() == "html":
                html_content = await self.report_formatter.format_report(report, "html")
                file_info = await self.file_manager.save_text_as_file(
                    html_content, f"deep_research_report_{task_id[:8]}.html", "html"
                )
                await event.send(f"🌐 报告HTML网页已生成：{file_info['file_url']}")
            elif format_type.lower() == "image":
                image_url = await self.report_formatter.format_report(report, "image")
                await event.send("🖼️ 报告图片已生成：")
                await event.send(MessageEventResult(chain=[Image.fromURL(image_url)]))
            else:
                await event.send(f"❌ 暂不支持的报告格式：`{format_type}`")
        except Exception as e:
            self.logger.error(
                f"发送报告输出失败 (任务 {task_id}, 格式 {format_type}): {e}",
                exc_info=True,
            )
            await event.send(f"❌ 发送报告失败，请联系管理员。错误：{e}")

    def get_task_status(self, task_id: str) -> Optional[DeepResearchTask]:
        """根据任务ID获取任务状态。"""
        return self.active_tasks.get(task_id)

    def cleanup_task(self, task_id: str):
        """
        清理已完成或失败的任务。
        可以用于释放资源或从活跃任务列表中移除。
        """
        if task_id in self.task_futures:
            self.task_futures[task_id].cancel()
            del self.task_futures[task_id]
        if task_id in self.active_tasks:
            # 根据需求，可以选择保留已完成/失败的任务数据一段时间，或者立即删除
            self.logger.info(f"任务 {task_id} 已从活跃任务列表中清理。")
            # del self.active_tasks[task_id] # 暂时不删除，方便用户查询历史状态

    def _extract_complete_search_config(self) -> Dict[str, Any]:
        """提取完整的搜索配置"""
        search_config = {}

        # 提取各种搜索引擎的配置
        config_sections = [
            "google_search",
            "bing_search",
            "serper_search",
            "baidu_search",
            "news_search",
            "academic_search",
        ]

        for section in config_sections:
            section_config = self.config.get(section, {})
            for key, value in section_config.items():
                # 构建统一的配置键名
                if section == "google_search":
                    if key == "cse_api_key":
                        search_config["google_cse_api_key"] = value
                    elif key == "cse_cx":
                        search_config["google_cse_cx"] = value
                elif section == "bing_search":
                    if key == "api_key":
                        search_config["bing_api_key"] = value
                    elif key == "endpoint":
                        search_config["bing_endpoint"] = value
                elif section == "serper_search":
                    if key == "api_key":
                        search_config["serper_api_key"] = value
                elif section == "baidu_search":
                    if key == "api_key":
                        search_config["baidu_api_key"] = value
                    elif key == "secret_key":
                        search_config["baidu_secret_key"] = value
                elif section == "news_search":
                    if key == "news_api_key":
                        search_config["news_api_key"] = value
                elif section == "academic_search":
                    if key == "semantic_scholar_api_key":
                        search_config["academic_search_api_key"] = value

        # 保持向后兼容性
        old_search_config = self.config.get("search_config", {})
        search_config.update(old_search_config)

        return search_config
