import asyncio
import uuid
from typing import Dict, Optional, List
from datetime import datetime

from astrbot.api import star, logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import Plain, Image

# 导入所有需要协调的模块
from deepresearch.data_models import (
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
from deepresearch.llm_modules.query_parser import QueryParser
from deepresearch.llm_modules.content_selector import ContentSelector
from deepresearch.llm_modules.document_processor import DocumentProcessor
from deepresearch.llm_modules.report_generator import ReportGenerator
from deepresearch.retrieval.web_search import WebSearchRetriever
from deepresearch.retrieval.news_api import NewsAPIRetriever
from deepresearch.retrieval.academic_search import AcademicSearchRetriever

# from deepresearch.retrieval.custom_db_adapter import CustomDBAdapter # 如果有的话
from deepresearch.content_processing.html_extractor import HTMLExtractor
from deepresearch.output_formatter.report_formatter import (
    ReportFormatter,
)  # 包含md转html和html渲染图片
from deepresearch.output_formatter.file_manager import FileManager


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
        self.web_search_retriever = WebSearchRetriever(context, config)
        self.news_api_retriever = NewsAPIRetriever(context, config)
        self.academic_search_retriever = AcademicSearchRetriever(context, config)
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

            # 阶段2: 多源信息检索
            task.update_status("retrieving_sources")
            await event.send(
                f"🔍 任务 `{task.task_id[:8]}`：正在从多源（网络、新闻、学术）检索信息..."
            )
            all_retrieved_items: List[RetrievedItem] = []
            if query_analysis_result.planned_search_queries.get("web"):
                for query in query_analysis_result.planned_search_queries["web"]:
                    all_retrieved_items.extend(
                        await self.web_search_retriever.search(
                            query, self.config.get("search_config", {})
                        )
                    )
            if query_analysis_result.planned_search_queries.get("news"):
                for query in query_analysis_result.planned_search_queries["news"]:
                    all_retrieved_items.extend(
                        await self.news_api_retriever.search(
                            query, self.config.get("search_config", {})
                        )
                    )
            if query_analysis_result.planned_search_queries.get("academic"):
                for query in query_analysis_result.planned_search_queries["academic"]:
                    all_retrieved_items.extend(
                        await self.academic_search_retriever.search(
                            query, self.config.get("search_config", {})
                        )
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

            for item in retrieval_output.unique_retrieved_items:
                extracted_text = await self.html_extractor.extract_text(item.url)
                processed_item = ProcessedContent(
                    retrieved_item=item,
                    extracted_text=extracted_text,
                    fetch_time=datetime.now(),
                )
                processed_contents.append(processed_item)

                # LLM筛选相关性 (可以先抓取再筛选，也可以先筛选再抓取，这里选择先抓取再筛选)
                is_relevant, score = await self.content_selector.check_relevance(
                    query_analysis_result, item, extracted_text
                )
                processed_item.is_relevant = is_relevant
                processed_item.relevance_score = score
                if is_relevant:
                    relevant_contents.append(processed_item)

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

            source_insights: List[SourceInsight] = []
            for doc in relevant_contents:
                if doc.extracted_text:
                    insights = (
                        await self.document_processor.process_and_summarize_document(
                            query_analysis_result, doc
                        )
                    )
                    source_insights.extend(insights)
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
                    file_url = await self.file_manager.save_text_as_file(
                        md_content, f"deep_research_report_{task_id}.md"
                    )
                    await event.send(f"报告Markdown文件已上传至临时存储：{file_url}")
                else:
                    await event.send(f"```markdown\n{md_content}\n```")
            elif format_type.lower() == "html":
                html_content = await self.report_formatter.format_report(report, "html")
                file_url = await self.file_manager.save_text_as_file(
                    html_content, f"deep_research_report_{task_id}.html"
                )
                await event.send(f"报告HTML网页已上传至临时存储：{file_url}")
                await event.send(
                    "[点击查看交互式报告](TODO_INTERACTIVE_REPORT_URL)"
                )  # 交互式报告需要部署前端
            elif format_type.lower() == "image":
                image_url = await self.report_formatter.format_report(report, "image")
                await event.send("报告图片已生成：")
                await event.send(MessageEventResult(chain=[Image.fromURL(image_url)]))
            else:
                await event.send(f"暂不支持的报告格式：`{format_type}`。")
        except Exception as e:
            self.logger.error(
                f"发送报告输出失败 (任务 {task_id}, 格式 {format_type}): {e}",
                exc_info=True,
            )
            await event.send(f"发送报告失败，请联系管理员。错误：{e}")

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
