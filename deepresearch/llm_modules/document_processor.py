import json
from typing import List, Dict, Any
from collections import defaultdict

from astrbot.api import star,logger, AstrBotConfig
from deepresearch.llm_modules.base_llm_module import BaseLLMModule
from deepresearch.data_models import (
    QueryAnalysisResult,
    ProcessedContent,
    SourceInsight,
    SubTopicSynthesis,
)
from deepresearch.utils import Utils


class DocumentProcessor(BaseLLMModule):
    """
    负责对抓取到的文档内容进行 LLM 处理，包括超大文档切块、小文档拼接、生成内容摘要，
    并最终按子主题进行综合。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.max_document_chunk_size = self.config.get("llm_config", {}).get(
            "max_document_chunk_size", 4000
        )
        self.min_doc_for_chunking = self.config.get("llm_config", {}).get(
            "min_doc_for_chunking", 6000
        )
        logger.info(
            f"DocumentProcessor 模块初始化完成。文档切块大小: {self.max_document_chunk_size}，最小切块文档大小: {self.min_doc_for_chunking}"
        )

    async def _chunk_text(self, text: str) -> List[str]:
        """
        将超长文本切分为多个文本块。
        这里使用简单的基于字符长度的切分，实际中可能需要基于 token 或语义切分。
        """
        chunks = []
        if len(text) <= self.min_doc_for_chunking:
            return [text]  # 小文档不切块

        start = 0
        while start < len(text):
            end = min(start + self.max_document_chunk_size, len(text))
            # 尝试在句子末尾或段落末尾切分，避免截断
            if end < len(text):
                # 寻找上一个句号或换行符
                ideal_split_point = text.rfind(".", start, end)
                if ideal_split_point == -1:
                    ideal_split_point = text.rfind("\n", start, end)

                if ideal_split_point != -1 and (end - ideal_split_point) < (
                    self.max_document_chunk_size * 0.2
                ):  # 避免切分过短
                    end = ideal_split_point + 1  # 包含句号或换行符

            chunks.append(text[start:end].strip())
            start = end
        logger.debug(f"文档已切分为 {len(chunks)} 个文本块。")
        return chunks

    async def process_and_summarize_document(
        self, query_analysis: QueryAnalysisResult, doc: ProcessedContent
    ) -> List[SourceInsight]:
        """
        处理单个文档，进行文本切块（如果需要），并调用 LLM 提取核心观点和事实。
        一个文档可能生成多个 SourceInsight，如果它关联到多个子主题。
        """
        if not doc.extracted_text:
            logger.warning(
                f"文档 '{doc.retrieved_item.url}' 无提取文本，跳过处理。"
            )
            return []

        cleaned_text = Utils.cleanup_text(doc.extracted_text)
        if not cleaned_text:
            logger.warning(
                f"文档 '{doc.retrieved_item.url}' 提取文本为空或无法清理，跳过处理。"
            )
            return []

        chunks = await self._chunk_text(cleaned_text)
        insights: List[SourceInsight] = []

        # 遍历所有子主题，为每个子主题从文档中提取相关洞察
        for sub_topic in query_analysis.identified_sub_topics:
            logger.debug(
                f"从文档 '{doc.retrieved_item.url[:50]}...' 为子主题 '{sub_topic}' 提取洞察。"
            )

            # 针对每个子主题，可能需要对每个chunk进行提炼
            # 更复杂的逻辑可能会先识别相关chunk，再进行总结
            # 这里简化为对每个chunk提取一次
            chunk_insights: List[Dict[str, Any]] = []
            for i, chunk in enumerate(chunks):
                prompt = f"""
你是一个研究助手，正在从文档中提取与特定子主题相关的核心观点和支持性引文。

原始研究问题: "{query_analysis.original_user_query.core_query}"
当前子主题: "{sub_topic}"

请从以下文本片段中，提取与上述子主题直接相关的：
1.  **key_points**: 简洁的核心观点或事实列表。
2.  **supporting_quotes**: 支持这些观点/事实的原文引用，保持其上下文。

输出严格为JSON格式，包含 "key_points" (列表) 和 "supporting_quotes" (列表)。
如果文本中没有与子主题相关的直接信息，请返回空列表。

文本片段（第 {i + 1} / {len(chunks)} 段）:
```
{chunk}
```
请确保输出严格符合JSON格式，不要包含任何额外文字，例如：
{{
    "key_points": ["观点1", "观点2"],
    "supporting_quotes": ["原文引用1...", "原文引用2..."]
}}
"""
                try:
                    llm_response_text = await self._text_chat_with_llm(prompt)
                    parsed_data = json.loads(llm_response_text)
                    chunk_insights.append(parsed_data)
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"文档处理 - LLM响应JSON解析失败 (子主题: {sub_topic}, URL: {doc.retrieved_item.url[:50]}...): {e}\n原始响应:\n{llm_response_text}",
                        exc_info=True,
                    )
                    continue  # 继续处理下一个 chunk

            # 将从所有 chunk 中提取的洞察合并
            aggregated_key_points = []
            aggregated_supporting_quotes = []
            for ci in chunk_insights:
                aggregated_key_points.extend(ci.get("key_points", []))
                aggregated_supporting_quotes.extend(ci.get("supporting_quotes", []))

            # 如果提取到有效信息，则创建一个 SourceInsight
            if aggregated_key_points:
                insights.append(
                    SourceInsight(
                        processed_content=doc,
                        sub_topic=sub_topic,
                        key_points=list(set(aggregated_key_points)),  # 去重
                        supporting_quotes=list(
                            set(aggregated_supporting_quotes)
                        ),  # 去重
                    )
                )
        return insights

    async def synthesize_by_sub_topic(
        self, query_analysis: QueryAnalysisResult, source_insights: List[SourceInsight]
    ) -> List[SubTopicSynthesis]:
        """
        按子主题聚合所有来源洞察，并生成综合摘要。
        """
        sub_topic_insights_map: Dict[str, List[SourceInsight]] = defaultdict(list)
        for insight in source_insights:
            sub_topic_insights_map[insight.sub_topic].append(insight)

        syntheses: List[SubTopicSynthesis] = []

        for sub_topic_name in query_analysis.identified_sub_topics:
            insights_for_topic = sub_topic_insights_map[sub_topic_name]
            if not insights_for_topic:
                logger.info(f"子主题 '{sub_topic_name}' 无相关洞察，跳过综合。")
                syntheses.append(
                    SubTopicSynthesis(
                        sub_topic_name=sub_topic_name,
                        synthesized_summary="未找到足够信息进行总结。",
                    )
                )
                continue

            logger.info(
                f"正在综合子主题 '{sub_topic_name}' 的洞察，共 {len(insights_for_topic)} 条。"
            )

            # 构造用于 LLM 综合的输入
            context_for_llm = []
            referenced_urls = set()
            for insight in insights_for_topic:
                context_for_llm.append(
                    f"来源: {insight.processed_content.retrieved_item.url}\n核心观点: {'; '.join(insight.key_points)}\n引用: {' '.join(insight.supporting_quotes)}"
                )
                referenced_urls.add(insight.processed_content.retrieved_item.url)

            combined_insights_text = "\n\n---\n\n".join(context_for_llm)

            prompt = f"""
你是一个高级研究分析师，需要综合多个信息来源的洞察，为特定子主题生成一份简洁、全面、客观的总结。

原始研究问题: "{query_analysis.original_user_query.core_query}"
当前子主题: "{sub_topic_name}"

以下是从不同来源提取的与此子主题相关的核心观点和支持性引用：
```
{combined_insights_text}
```

请根据上述信息，生成一份针对 "{sub_topic_name}" 的综合总结。
总结应包含：
1.  **synthesized_summary**: 对该子主题的整体概述和关键发现。
2.  **consistent_findings**: 如果有，列出不同来源都提及或支持的共同观点。
3.  **conflicting_findings**: 如果有，列出不同来源之间存在的矛盾或不一致的观点 (简要说明)。

请确保输出严格符合JSON格式，不要包含任何额外文字，例如：
{{
  "synthesized_summary": "...",
  "consistent_findings": ["...", "..."],
  "conflicting_findings": ["...", "..."]
}}
"""
            try:
                llm_response_text = await self._text_chat_with_llm(prompt)
                parsed_data = json.loads(llm_response_text)

                syntheses.append(
                    SubTopicSynthesis(
                        sub_topic_name=sub_topic_name,
                        insights_from_sources=insights_for_topic,
                        synthesized_summary=parsed_data.get(
                            "synthesized_summary", "未能生成有效总结。"
                        ),
                        consistent_findings=parsed_data.get("consistent_findings", []),
                        conflicting_findings=parsed_data.get(
                            "conflicting_findings", []
                        ),
                        referenced_urls=list(referenced_urls),
                    )
                )
            except json.JSONDecodeError as e:
                logger.warning(
                    f"子主题 '{sub_topic_name}' 综合响应JSON解析失败: {e}\n原始响应:\n{llm_response_text}",
                    exc_info=True,
                )
                syntheses.append(
                    SubTopicSynthesis(
                        sub_topic_name=sub_topic_name,
                        insights_from_sources=insights_for_topic,
                        synthesized_summary="LLM总结失败，请检查日志。",
                        referenced_urls=list(referenced_urls),
                    )
                )
            except Exception as e:
                logger.error(
                    f"子主题 '{sub_topic_name}' 综合失败: {e}", exc_info=True
                )
                syntheses.append(
                    SubTopicSynthesis(
                        sub_topic_name=sub_topic_name,
                        insights_from_sources=insights_for_topic,
                        synthesized_summary=f"发生错误，总结失败: {e}",
                        referenced_urls=list(referenced_urls),
                    )
                )
        return syntheses
