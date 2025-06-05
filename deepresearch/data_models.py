from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple, Literal
from datetime import datetime
from astrbot.api.platform import MessageMember
from astrbot.api import logger

# --- Phase 1: 用户需求与初步规划 ---


@dataclass
class UserResearchQuery:
    """
    封装用户输入的原始研究需求。
    """

    core_query: str  # 核心查询 (Query): 用户想要研究的主题或问题
    # (可选) 研究深度/范围限定，例如："浅层概述", "中等深度分析", "深入研究报告"
    depth_limit: Optional[str] = None
    # (可选) 时间范围，例如："最近一周", "最近一个月", "不限时间"
    time_scope: Optional[str] = None
    # (可选) 偏好来源，例如：["学术论文"], ["新闻", "博客"], ["综合来源"]
    source_preference: Optional[List[str]] = None
    # (可选) 期望输出格式提示
    output_format_hint: Optional[str] = None
    request_time: datetime = field(default_factory=datetime.now)  # 请求发起时间
    user_id: Optional[MessageMember] = None

    def __post_init__(self):
        logger.info(
            f"接收到新的研究请求: 核心查询='{self.core_query}', 用户ID='{self.user_id}'"
        )


@dataclass
class QueryAnalysisResult:
    """
    LLM对用户查询进行解析和扩展后的结果。
    """

    original_user_query: UserResearchQuery  # 原始用户请求，方便追溯
    extracted_keywords: List[str]  # 从用户查询中识别的核心关键词
    expanded_terms: List[str]  # 扩展的同义词、上位词、下位词等
    identified_sub_topics: List[str]  # LLM分解出的相关子主题或子问题
    # search_strategy_notes: str                # 初步确定的搜索策略文字描述 (LLM生成)
    # 实际的搜索查询，按来源类型组织
    planned_search_queries: Dict[
        Literal["web", "academic", "news", "custom"], List[str]
    ] = field(default_factory=dict)

    def __post_init__(self):
        logger.info(
            f"查询 '{self.original_user_query.core_query[:30]}...' 解析完成。关键词: {self.extracted_keywords}, 子主题: {self.identified_sub_topics}"
        )


# --- Phase 2: 多源信息检索 ---


@dataclass
class RetrievedItem:
    """
    从单个信息来源检索到的初步结果。
    """

    url: str  # 信息的URL
    source_type: Literal["web", "academic", "news", "custom"]  # 信息来源类型
    title: Optional[str] = None  # 网页标题
    snippet: Optional[str] = None  # 搜索结果摘要或内容片段
    retrieval_time: datetime = field(default_factory=datetime.now)  # 获取时间
    raw_source_data: Optional[Any] = None  # 原始API返回数据，方便调试

    # 新增字段以支持搜索引擎处理
    metadata: Optional[Dict[str, Any]] = None  # 元数据字典，存储额外信息
    content: Optional[str] = None  # 提取的完整内容（用于内容提取后存储）
    relevance_score: float = 0.0  # 相关性评分
    published_date: Optional[datetime] = None  # 发布时间
    source: str = "unknown"  # 具体的搜索引擎来源标识

    def __post_init__(self):
        logger.debug(
            f"检索到项目: URL='{self.url}', 类型='{self.source_type}', 来源='{self.source}'"
        )

        # 如果没有设置source，根据source_type设置默认值
        if self.source == "unknown":
            self.source = self.source_type


@dataclass
class RetrievalPhaseOutput:
    """
    多源信息检索阶段的完整输出。
    """

    query_analysis: QueryAnalysisResult  # 对应的查询分析结果
    all_retrieved_items: List[RetrievedItem] = field(
        default_factory=list
    )  # 所有来源返回的条目
    unique_retrieved_items: List[RetrievedItem] = field(
        default_factory=list
    )  # URL去重后的条目

    def perform_deduplication(self):
        """进行URL去重"""
        seen_urls = set()
        self.unique_retrieved_items = []
        for item in self.all_retrieved_items:
            if item.url not in seen_urls:
                self.unique_retrieved_items.append(item)
                seen_urls.add(item.url)
        logger.info(
            f"检索结果去重: 从 {len(self.all_retrieved_items)} 条到 {len(self.unique_retrieved_items)} 条唯一项目。"
        )


# --- Phase 3: 内容提取与预处理 ---


@dataclass
class ProcessedContent:
    """
    经过筛选、抓取和文本提取处理后的单个信息源内容。
    """

    retrieved_item: RetrievedItem  # 对应的原始检索条目
    is_relevant: Optional[bool] = None  # LLM评估的相关性 (True/False)
    relevance_score: Optional[float] = None  # LLM评估的相关性分数 (如果LLM能输出分数)
    extracted_text: Optional[str] = None  # 从网页中提取的主要纯文本内容
    # content_chunks: Optional[List[str]] = None # (可选) 文本分块
    # vector_embeddings: Optional[Any] = None   # (可选) 文本块的向量表示 (例如 List[List[float]])
    processing_error: Optional[str] = None  # 如果处理失败，记录错误信息
    fetch_time: Optional[datetime] = None  # 内容抓取时间

    def __post_init__(self):
        status = (
            "成功" if not self.processing_error else f"失败({self.processing_error})"
        )
        relevance_info = (
            f"相关性: {self.is_relevant}"
            if self.is_relevant is not None
            else "相关性未评估"
        )
        logger.debug(
            f"内容处理: URL='{self.retrieved_item.url}', 状态='{status}', {relevance_info}"
        )


# --- Phase 4: 信息分析与综合 ---


@dataclass
class SourceInsight:
    """
    针对单个来源内容，LLM提取的核心观点/事实。
    """

    processed_content: ProcessedContent  # 对应的已处理内容
    sub_topic: str  # 此观点关联的子主题 (来自QueryAnalysisResult)
    key_points: List[str]  # 提取的核心观点、事实列表
    supporting_quotes: List[str] = field(default_factory=list)  # 支持观点的原文引用
    # data_points: List[Dict[str, Any]] = field(default_factory=list) # 提取出的结构化数据点
    llm_confidence: Optional[float] = None  # LLM对提取内容准确性的信心（如果可获取）

    def __post_init__(self):
        logger.debug(
            f"来源洞察提取: URL='{self.processed_content.retrieved_item.url}', 子主题='{self.sub_topic}', 提取点数: {len(self.key_points)}"
        )


@dataclass
class SubTopicSynthesis:
    """
    针对一个子主题，综合多个来源信息后形成的分析。
    """

    sub_topic_name: str
    # 汇总的来自不同来源的关于此子主题的观点
    insights_from_sources: List[SourceInsight] = field(default_factory=list)
    # LLM生成的该子主题的摘要或章节初稿
    synthesized_summary: Optional[str] = None
    # (可选) 识别出的一致观点
    consistent_findings: List[str] = field(default_factory=list)
    # (可选) 识别出的矛盾观点
    conflicting_findings: List[Tuple[SourceInsight, SourceInsight, str]] = field(
        default_factory=list
    )  # (来源A, 来源B, 矛盾描述)
    # (可选) 独特的补充信息
    unique_perspectives: List[SourceInsight] = field(default_factory=list)
    # (可选) 初步的可信度评估
    credibility_assessment_notes: Optional[str] = None
    # 引用了哪些来源的URL来形成这个子主题的综合
    referenced_urls: List[str] = field(default_factory=list)

    def __post_init__(self):
        logger.info(
            f"子主题综合完成: '{self.sub_topic_name}', 包含 {len(self.insights_from_sources)} 条来源洞察。"
        )


# --- Phase 5: 研究报告生成与润色 ---


@dataclass
class ReportSection:
    """
    研究报告中的一个章节。
    """

    title: str  # 章节标题 (例如：引言, AI在疾病诊断的应用, 结论)
    content: str  # 章节内容 (Markdown格式)
    # (可选) 章节类型，方便后续处理
    section_type: Literal[
        "introduction", "sub_topic_body", "conclusion", "references", "methodology"
    ] = "sub_topic_body"


@dataclass
class ResearchReport:
    """
    最终生成的研究报告。
    """

    original_user_query: UserResearchQuery  # 原始用户请求
    query_analysis: QueryAnalysisResult  # 查询分析结果
    # sub_topic_syntheses: List[SubTopicSynthesis] # 各子主题的综合分析 (用于生成报告主体)
    main_title: str  # 报告主标题
    sections: List[ReportSection] = field(default_factory=list)  # 报告的各个章节
    # (可选) 报告的整体摘要
    # executive_summary: Optional[str] = None
    generation_time: datetime = field(default_factory=datetime.now)
    # all_cited_sources: List[RetrievedItem] = field(default_factory=list) # 报告中所有被引用的来源

    def get_full_markdown_content(self) -> str:
        """将报告所有章节内容合并为一个完整的Markdown字符串"""
        report_md = f"# {self.main_title}\n\n"
        for section in self.sections:
            # 根据section_type选择合适的Markdown标题级别
            if (
                section.section_type == "introduction"
                or section.section_type == "conclusion"
            ):
                report_md += f"## {section.title}\n\n{section.content}\n\n"
            elif section.section_type == "sub_topic_body":
                report_md += f"### {section.title}\n\n{section.content}\n\n"
            elif section.section_type == "references":
                report_md += (
                    f"## {section.title}\n\n{section.content}\n\n"  # 通常参考文献是列表
                )
            else:
                report_md += f"## {section.title}\n\n{section.content}\n\n"
        logger.info(f"研究报告 '{self.main_title}' Markdown内容已生成。")
        return report_md

    def __post_init__(self):
        logger.info(
            f"研究报告 '{self.main_title}' 结构已创建。包含 {len(self.sections)} 个章节。"
        )


# --- 整个研究任务的容器 (可选，但推荐) ---
@dataclass
class DeepResearchTask:
    """
    代表一个完整的DeepResearch任务，用于跟踪整个流程的状态和数据。
    """

    task_id: str  # 唯一任务ID，可以用uuid生成
    user_query: UserResearchQuery
    status: Literal[
        "pending_analysis",
        "analyzing_query",
        "pending_retrieval",
        "retrieving_sources",
        "pending_processing",
        "processing_content",
        "pending_synthesis",
        "synthesizing_insights",
        "pending_report_generation",
        "generating_report",
        "completed",
        "failed",
    ] = "pending_analysis"
    error_message: Optional[str] = None

    # 各阶段的产出物
    query_analysis_result: Optional[QueryAnalysisResult] = None
    retrieval_output: Optional[RetrievalPhaseOutput] = None
    processed_contents: List[ProcessedContent] = field(
        default_factory=list
    )  # 所有被处理（尝试处理）的内容
    relevant_contents: List[ProcessedContent] = field(
        default_factory=list
    )  # 筛选出的相关内容
    source_insights: List[SourceInsight] = field(default_factory=list)  # 所有来源的洞察
    sub_topic_syntheses: List[SubTopicSynthesis] = field(
        default_factory=list
    )  # 所有子主题的综合分析
    final_report: Optional[ResearchReport] = None

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def update_status(self, new_status: str, error_msg: Optional[str] = None):
        self.status = new_status  # type: ignore
        self.updated_at = datetime.now()
        if error_msg:
            self.error_message = error_msg
        logger.info(
            f"任务 {self.task_id} 状态更新为: {self.status}"
            + (f", 错误: {error_msg}" if error_msg else "")
        )
