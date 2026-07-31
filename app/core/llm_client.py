"""
共享 LLM 客户端工厂

Phase 5 P2: 支持多 provider（ollama / deepseek / qwen / openai）。
返回 (client, model_name) 元组，调用方无需感知 provider 差异。
"""
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


def _get_model_name(purpose: str) -> str:
    """根据 provider + purpose 返回正确的模型名"""
    provider = settings.LLM_PROVIDER

    if purpose == "embed":
        # Embedding 始终走本地 Ollama，与 LLM provider 无关
        return settings.EMBEDDING_MODEL
    if provider == "ollama":
        if purpose == "agent":
            return settings.AGENT_MODEL
        else:
            return settings.LLM_MODEL_NAME
    else:
        if purpose == "agent":
            return settings.CLOUD_AGENT_MODEL
        else:
            return settings.CLOUD_MODEL_NAME


@lru_cache(maxsize=4)
def get_llm_client(purpose: str = "default") -> tuple[AsyncOpenAI, str]:
    """获取 (AsyncOpenAI 客户端, 模型名) 元组

    lru_cache 基于 purpose 参数做缓存，maxsize=4 覆盖四种组合。
    调用方解构: client, model_name = get_llm_client("agent")
    """
    provider = settings.LLM_PROVIDER

    if purpose == "embed":
        # Embedding 始终走本地 Ollama，与 LLM provider 无关
        base_url = settings.OLLAMA_BASE_URL
        api_key = settings.OLLAMA_API_KEY
    elif provider == "ollama":
        base_url = settings.LLM_BASE_URL
        api_key = settings.LLM_API_KEY
    elif provider == "deepseek":
        base_url = settings.CLOUD_BASE_URL or "https://api.deepseek.com/v1"
        api_key = settings.CLOUD_API_KEY
    elif provider == "qwen":
        base_url = settings.CLOUD_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        api_key = settings.CLOUD_API_KEY
    elif provider == "openai":
        base_url = settings.CLOUD_BASE_URL or "https://api.openai.com/v1"
        api_key = settings.CLOUD_API_KEY
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")

    if purpose == "agent":
        timeout = settings.AGENT_TIMEOUT_SECONDS
    elif purpose == "embed":
        timeout = settings.EMBEDDING_TIMEOUT_SECONDS
    else:
        timeout = settings.LLM_TIMEOUT_SECONDS

    client = AsyncOpenAI(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=timeout,
        max_retries=settings.LLM_MAX_RETRIES,
    )
    model_name = _get_model_name(purpose)
    return client, model_name
