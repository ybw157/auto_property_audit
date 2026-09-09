import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from langchain.chat_models import init_chat_model

logger = logging.getLogger(__name__)

ENV_LLM_API_KEY = "LLM_API_KEY"
ENV_LLM_BASE_URL = "LLM_BASE_URL"


@dataclass
class ModelConfig:
    model_name: str
    temperature: float = 0.1
    max_tokens: int = 4096
    description: str = ""


class ModelRegistry:
    models: dict[str, ModelConfig] = {
        "deepseek-v4-pro": ModelConfig(
            model_name="deepseek-v4-pro",
            temperature=0.1,
            max_tokens=4096,
            description="主力模型：结构化提取、复杂推理",
        ),
        "deepseek-v4-flash": ModelConfig(
            model_name="deepseek-v4-flash",
            temperature=0.0,
            max_tokens=2048,
            description="轻量模型：简单任务、快速响应",
        ),
        "qwen3.7-plus": ModelConfig(
            model_name="qwen3.7-plus",
            temperature=0.1,
            max_tokens=4096,
            description="视觉模型：OCR 页面文字提取",
        ),
        "qwen3.6-plus": ModelConfig(
            model_name="qwen3.6-plus",
            temperature=0.1,
            max_tokens=4096,
            description="备用降级模型",
        ),
        "glm-5.2": ModelConfig(
            model_name="glm-5.2",
            temperature=0.1,
            max_tokens=4096,
            description="视觉模型备选",
        ),
        "glm-5.1": ModelConfig(
            model_name="glm-5.1",
            temperature=0.1,
            max_tokens=4096,
            description="视觉模型备选",
        ),
        "kimi-k2.6": ModelConfig(
            model_name="kimi-k2.6",
            temperature=0.1,
            max_tokens=4096,
            description="通用备选模型",
        ),
        "kimi-k2.7-code": ModelConfig(
            model_name="kimi-k2.7-code",
            temperature=0.0,
            max_tokens=4096,
            description="代码场景模型，不推荐用于合同解析",
        ),
    }

    default_model: str = "deepseek-v4-pro"
    fallback_chain: list[str] = field(default_factory=lambda: ["qwen3.7-plus", "deepseek-v4-flash"])


class LLMFactory:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        registry: Optional[ModelRegistry] = None,
    ):
        self.api_key = api_key or os.getenv(ENV_LLM_API_KEY, "")
        self.base_url = base_url or os.getenv(ENV_LLM_BASE_URL, "")
        self.registry = registry or ModelRegistry()

    def validate(self) -> bool:
        if not self.api_key:
            logger.error(
                f"LLM API Key 未配置！请在 .env 文件中设置 {ENV_LLM_API_KEY}，"
                f"或通过环境变量导出 {ENV_LLM_API_KEY}=your_key"
            )
            return False
        if not self.base_url:
            logger.warning(
                f"LLM Base URL 未配置，将使用各模型默认地址。"
                f"如需自定义，请在 .env 文件中设置 {ENV_LLM_BASE_URL}"
            )
        logger.info(
            f"LLM 配置已加载: base_url={self.base_url or '(默认)'}, "
            f"默认模型={self.registry.default_model}, "
            f"可用模型={list(self.registry.models.keys())}"
        )
        return True

    def create(self, model_key: Optional[str] = None, **kwargs):
        model_key = model_key or self.registry.default_model
        config = self.registry.models.get(model_key)
        if not config:
            raise ValueError(
                f"未知模型: {model_key}，可用模型: {list(self.registry.models.keys())}"
            )

        return init_chat_model(
            model=config.model_name,
            model_provider="openai",
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=kwargs.pop("temperature", config.temperature),
            max_tokens=kwargs.pop("max_tokens", config.max_tokens),
            **kwargs,
        )

    def create_with_fallback(self, model_keys: Optional[list[str]] = None):
        keys = model_keys or [self.registry.default_model] + self.registry.fallback_chain
        last_error = None
        for key in keys:
            try:
                return self.create(key)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"所有模型均不可用，最后错误: {last_error}")

    def list_models(self) -> dict[str, str]:
        return {k: v.description for k, v in self.registry.models.items()}


llm_factory = LLMFactory()