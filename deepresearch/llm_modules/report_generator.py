import json
from typing import List

from astrbot.api import star,logger, AstrBotConfig
from deepresearch.llm_modules.base_llm_module import BaseLLMModule
from deepresearch.data_models import (
    UserResearchQuery,
    QueryAnalysisResult,
    SubTopicSynthesis,
    ResearchReport,
    ReportSection,
)


class ReportGenerator(BaseLLMModule):
    """
    负责聚合分析所有子主题总结，并生成最终的研究报告（Markdown格式）。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("ReportGenerator 模块初始化完成。")

    async def generate_full_report(
        self,
        user_query: UserResearchQuery,
        query_analysis: QueryAnalysisResult,
        sub_topic_syntheses: List[SubTopicSynthesis],
    ) -> ResearchReport:
        """
        生成完整的Markdown格式研究报告。
        """
        logger.info("开始生成完整研究报告。")

        # 构造报告内容给 LLM
        report_sections_input = []
        for s in sub_topic_syntheses:
            section_content = f"### {s.sub_topic_name}\n\n{s.synthesized_summary}\n\n"
            if s.consistent_findings:
                section_content += (
                    "**共同发现:**\n"
                    + "\n".join([f"- {f}" for f in s.consistent_findings])
                    + "\n\n"
                )
            if s.conflicting_findings:
                section_content += (
                    "**争议点:**\n"
                    + "\n".join([f"- {f}" for f in s.conflicting_findings])
                    + "\n\n"
                )

            # 整合引用的URL
            if s.referenced_urls:
                section_content += (
                    "**参考来源:**\n"
                    + "\n".join([f"- <{url}>" for url in s.referenced_urls])
                    + "\n\n"
                )

            report_sections_input.append(section_content)

        combined_body_content = "\n---\n".join(report_sections_input)

        # 提取所有独特的引用URL用于最终参考文献列表
        all_referenced_urls = set()
        for s in sub_topic_syntheses:
            all_referenced_urls.update(s.referenced_urls)

        # 生成报告主标题
        main_title_prompt = f"根据用户研究问题 '{user_query.core_query}' 和已解析的子主题 {query_analysis.identified_sub_topics}，生成一个适合作为研究报告主标题的简洁标题，不要包含任何额外文字。"
        main_title = (await self._text_chat_with_llm(main_title_prompt)).strip()
        if not main_title or len(main_title) > 100:  # 避免LLM乱回复
            main_title = f"关于“{user_query.core_query}”的深度研究报告"

        # 准备 LLM 提示词来生成完整报告结构（引言、结论）
        prompt = f"""
你是一个专业的报告撰写专家，需要根据以下信息生成一份结构完整、逻辑清晰的深度研究报告。

报告应包含以下结构：
1.  **main_title**: 报告的主标题。
2.  **sections**: 一个列表，每个元素是一个章节对象，包含 'title', 'content', 'section_type'。
    -   'introduction' (引言): 介绍报告背景、目的和研究范围。
    -   'sub_topic_body' (主体内容): 结合提供的子主题总结和分析。
    -   'conclusion' (结论与展望): 总结主要发现，提出局限性或未来展望。
    -   'references' (参考文献): 列出所有引用的链接。

请确保输出严格符合JSON格式，不要包含任何额外文字。

原始研究问题: "{user_query.core_query}"
LLM解析结果（子主题、拓展问题等）: {query_analysis.identified_sub_topics}
各子主题的综合分析（部分内容已整合，您需要据此生成报告主体部分，并补充引言和结论）：
```
{combined_body_content}
```
已引用的所有链接: {list(all_referenced_urls)}

请生成最终的JSON报告结构，例如：
{{
  "main_title": "...",
  "sections": [
    {{
      "title": "引言",
      "content": "...",
      "section_type": "introduction"
    }},
    {{
      "title": "AI在疾病诊断",
      "content": "...",
      "section_type": "sub_topic_body"
    }},
    ...
    {{
      "title": "结论与展望",
      "content": "...",
      "section_type": "conclusion"
    }},
    {{
      "title": "参考文献",
      "content": "- [链接1](url1)\n- [链接2](url2)",
      "section_type": "references"
    }}
  ]
}}
"""
        try:
            llm_response_text = await self._text_chat_with_llm(prompt)
            parsed_data = json.loads(llm_response_text)

            final_main_title = parsed_data.get("main_title", main_title)
            report_sections_data = parsed_data.get("sections", [])

            sections: List[ReportSection] = []
            for sec_data in report_sections_data:
                # 检查并确保引用部分是正确的格式
                if sec_data.get("section_type") == "references":
                    # LLM可能无法准确生成参考文献，我们在此强制生成
                    ref_content = "\n".join(
                        [f"- <{url}>" for url in sorted(all_referenced_urls)]
                    )
                    sections.append(
                        ReportSection(
                            title="参考文献",
                            content=ref_content,
                            section_type="references",
                        )
                    )
                else:
                    sections.append(
                        ReportSection(
                            title=sec_data.get("title", "未知章节"),
                            content=sec_data.get("content", "内容缺失。"),
                            section_type=sec_data.get("section_type", "sub_topic_body"),
                        )
                    )

            logger.info(f"成功生成报告 '{final_main_title}'。")
            return ResearchReport(
                original_user_query=user_query,
                query_analysis=query_analysis,
                main_title=final_main_title,
                sections=sections,
            )

        except json.JSONDecodeError as e:
            logger.error(
                f"LLM报告生成响应JSON解析失败: {e}\n原始响应:\n{llm_response_text}",
                exc_info=True,
            )
            raise RuntimeError("LLM未能生成有效的报告结构，请稍后再试。")
        except Exception as e:
            logger.error(f"生成完整研究报告失败: {e}", exc_info=True)
            raise
