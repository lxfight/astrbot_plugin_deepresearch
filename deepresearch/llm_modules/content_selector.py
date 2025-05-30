import json
from typing import Tuple

from astrbot.api import star, logger, AstrBotConfig
from deepresearch.llm_modules.base_llm_module import BaseLLMModule
from deepresearch.data_models import QueryAnalysisResult, RetrievedItem
from deepresearch.utils import Utils


class ContentSelector(BaseLLMModule):
    """
    使用 LLM 筛选检索到的信息条目，评估其与用户查询的相关性。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        logger.info("ContentSelector 模块初始化完成。")

    async def check_relevance(
        self,
        query_analysis: QueryAnalysisResult,
        item: RetrievedItem,
        extracted_text: str,
    ) -> Tuple[bool, float]:
        """
        评估单个检索条目（或其提取的文本）与原始查询的相关性。
        返回 (is_relevant, relevance_score)。
        """
        # 限制文本长度以节省LLM token
        text_preview = Utils.cleanup_text(extracted_text)
        if text_preview and len(text_preview) > 1500:
            text_preview = text_preview[:1500] + "..."  # 截断

        prompt = f"""
请评估以下信息源与原始研究问题之间的相关性。
请输出JSON格式的结果，包含一个布尔值 `is_relevant` 和一个 0.0 到 1.0 之间的浮点数 `relevance_score`。

原始研究问题: "{query_analysis.original_user_query.core_query}"
解析出的子主题: {query_analysis.identified_sub_topics}
核心关键词: {query_analysis.extracted_keywords}

信息源标题: "{item.title or "无标题"}"
信息源摘要/片段: "{item.snippet or "无摘要"}"
信息源链接: "{item.url}"
信息源提取文本预览: "{text_preview or "无文本预览"}"

请确保输出严格符合JSON格式，不要包含任何额外文字，例如：
{{
  "is_relevant": true,
  "relevance_score": 0.85
}}
"""
        try:
            llm_response_text = await self._text_chat_with_llm(prompt)
            parsed_data = json.loads(llm_response_text)

            is_relevant = parsed_data.get("is_relevant", False)
            relevance_score = float(parsed_data.get("relevance_score", 0.0))

            logger.debug(
                f"评估URL '{item.url[:50]}...' 相关性: {is_relevant}, 分数: {relevance_score}"
            )
            return is_relevant, relevance_score
        except json.JSONDecodeError as e:
            logger.warning(
                f"LLM相关性评估响应JSON解析失败: {e}\n原始响应:\n{llm_response_text}",
                exc_info=True,
            )
            return False, 0.0  # 解析失败，默认不相关
        except Exception as e:
            logger.error(
                f"评估相关性失败 for URL '{item.url[:50]}...': {e}", exc_info=True
            )
            return False, 0.0  # 发生其他错误，默认不相关
