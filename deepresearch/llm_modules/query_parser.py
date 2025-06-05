import json

from astrbot.api import star,logger, AstrBotConfig
from .base_llm_module import BaseLLMModule
from ..data_models import UserResearchQuery, QueryAnalysisResult


class QueryParser(BaseLLMModule):
    """
    负责使用 LLM 解析用户研究问题，并将其分解为子问题、子主题和生成搜索查询。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("QueryParser 模块初始化完成。")

    async def parse_query(self, user_query: UserResearchQuery) -> QueryAnalysisResult:
        """
        将用户查询发送给 LLM 进行解析，获取关键词、子主题和建议的搜索查询。
        """
        prompt = f"""
请根据以下用户研究问题，进行深入解析，并输出JSON格式的结果。
您需要识别以下几个方面：
1.  **extracted_keywords**: 核心关键词列表。
2.  **expanded_terms**: 围绕核心关键词的拓展词、同义词、或更具体的概念。
3.  **identified_sub_topics**: 根据用户问题，可能需要深入研究的子主题或子问题列表。
4.  **planned_search_queries**: 为每个搜索源（'web', 'academic', 'news'）生成至少2-3个具体的搜索查询词条。

用户研究问题: "{user_query.core_query}"

请确保输出严格符合JSON格式，不要包含任何额外文字，例如：
{{
    "extracted_keywords": ["..."],
    "expanded_terms": ["..."],
    "identified_sub_topics": ["...", "..."],
    "planned_search_queries": {{
        "web": ["...", "..."],
        "academic": ["...", "..."],
        "news": ["...", "..."]
    }}
}}
"""
        try:
            llm_response_text = await self._text_chat_with_llm(prompt)
            parsed_data = json.loads(llm_response_text)

            extracted_keywords = parsed_data.get("extracted_keywords", [])
            expanded_terms = parsed_data.get("expanded_terms", [])
            identified_sub_topics = parsed_data.get("identified_sub_topics", [])
            planned_search_queries = parsed_data.get("planned_search_queries", {})

            # 确保 planned_search_queries 包含所有期望的类型，即使为空
            for source_type in ["web", "academic", "news", "custom"]:
                if source_type not in planned_search_queries:
                    planned_search_queries[source_type] = []

            logger.info(f"成功解析用户查询 '{user_query.core_query[:30]}...'")
            return QueryAnalysisResult(
                original_user_query=user_query,
                extracted_keywords=extracted_keywords,
                expanded_terms=expanded_terms,
                identified_sub_topics=identified_sub_topics,
                planned_search_queries=planned_search_queries,
            )
        except json.JSONDecodeError as e:
            logger.error(
                f"LLM响应JSON解析失败: {e}\n原始响应:\n{llm_response_text}",
                exc_info=True,
            )
            raise RuntimeError("LLM未能生成有效的解析结果，请稍后再试。")
        except Exception as e:
            logger.error(f"解析用户查询失败: {e}", exc_info=True)
            raise
