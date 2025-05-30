from astrbot.api import star, logger, provider, AstrBotConfig
from deepresearch.base_module import BaseModule
from typing import Optional, List, Dict


class BaseLLMModule(BaseModule):
    """
    所有与 LLM 交互模块的基类。
    确保能够获取并使用 AstrBot 当前配置的 LLM 提供商。
    """

    def __init__(self, context: star.Context, config: AstrBotConfig):
        super().__init__(context, config)
        self._llm_provider: Optional[provider.Provider] = None
        self._llm_model_name: Optional[str] = self.config.get("llm_config", {}).get(
            "llm_model_name"
        )

    def get_llm_provider(self) -> provider.Provider:
        """
        获取当前 AstrBot 配置的 LLM 提供商实例。
        如果插件配置中指定了模型名称，可能会尝试根据模型名称选择。
        """
        if not self._llm_provider:
            # 优先使用插件配置指定的模型名称来获取LLM提供商
            # 实际的 provider manager 可能需要根据模型名称来获取
            # 暂时先用 get_using_provider()
            self._llm_provider = self.context.get_using_provider()
            if not self._llm_provider:
                logger.error(
                    "当前未配置可用的LLM提供商，请在AstrBot管理面板中配置。"
                )
                raise ValueError("未找到可用的大语言模型提供商。")
            logger.info(f"LLM 模块使用 LLM 提供商: {self._llm_provider.id}")
        return self._llm_provider

    async def _text_chat_with_llm(
        self,
        prompt: str,
        contexts: List[Dict[str, str]] = None,
        system_prompt: str = None,
    ) -> str:
        """
        封装底层 LLM 调用，提供统一接口。
        """
        llm = self.get_llm_provider()
        try:
            response = await llm.text_chat(
                prompt=prompt,
                contexts=contexts if contexts is not None else [],
                system_prompt=system_prompt if system_prompt is not None else "",
            )
            if response.role == "assistant":
                return response.completion_text
            else:
                logger.warning(
                    f"LLM 返回非助手角色响应: {response.role}, 原始响应: {response.raw_completion}"
                )
                return f"LLM响应异常: {response.raw_completion}"
        except Exception as e:
            logger.error(f"LLM调用失败: {e}", exc_info=True)
            raise RuntimeError(f"与大语言模型通信失败: {e}")
