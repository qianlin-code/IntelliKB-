"""
Query Rewrite 服务 —— LLM-based 查询改写

Phase 8: 三种重写策略
  策略 A (resolution): 指代消解 + 上下文补全（当前默认）
  策略 B (decomposition): 复杂问题拆解为 2-3 个子查询
  策略 C (keyword): 核心实体/关键词提取
"""
import hashlib
import json
import logging

from app.config import settings
from app.core.llm_client import get_llm_client
from app.core.redis_client import cache_get, cache_set

logger = logging.getLogger("app")

# Phase 8: 各策略的 prompt 模板
STRATEGY_PROMPTS = {
    "A": """将以下对话中的最后一条用户问题改写为独立、完整的问题。
改写规则：
1. 补全对话历史中的指代（如"它"→具体名词）
2. 保持原意不变
3. 用中文回答

对话历史：
{history_text}

用户问题：{question}
改写结果：""",

    "B": """将以下用户问题拆解为 2-3 个独立的子查询，用于知识库检索。
如果问题本身很简单，不要强行拆解。

拆解规则：
1. 每个子查询应该独立可检索
2. 覆盖原问题的不同方面
3. 每行一个子查询，不要编号

对话历史：
{history_text}

用户问题：{question}
子查询：""",

    "C": """从以下用户问题和对话历史中提取核心关键词和实体，用于知识库检索。

提取规则：
1. 只提取名词短语、专有名词、关键动词
2. 用空格分隔
3. 不要包含停用词

对话历史：
{history_text}

用户问题：{question}
关键词：""",
}


class QueryRewriteService:
    """LLM-based 查询改写

    Phase 8: 支持三种策略切换。
    """

    def __init__(self):
        self.client, self.model = get_llm_client(purpose="default")

    def _cache_key(self, question: str, history: list[dict], strategy: str = "A") -> str:
        """改写结果缓存键（含策略名）"""
        payload = json.dumps(
            {"q": question, "h": history, "s": strategy},
            ensure_ascii=False, sort_keys=True,
        )
        return f"qr:{hashlib.md5(payload.encode()).hexdigest()[:16]}"

    async def rewrite(
        self, question: str, history: list[dict] | None = None,
        strategy: str | None = None,
    ) -> str:
        """查询改写

        Args:
            question: 当前用户问题
            history: 对话历史 [{"role":"user","content":"..."}, ...]
            strategy: A=指代消解 B=问题拆解 C=关键词提取。默认取 QUERY_REWRITE_STRATEGY 配置。

        Returns:
            改写后的查询文本。策略 B 返回多行子查询（下游可 splitlines 使用）。
            若改写失败或无需改写，返回原始 question。
        """
        if not settings.QUERY_REWRITE_ENABLED:
            return question

        strategy = strategy or settings.QUERY_REWRITE_STRATEGY
        if strategy not in STRATEGY_PROMPTS:
            logger.warning("Unknown rewrite strategy '%s', falling back to A", strategy)
            strategy = "A"

        # 策略 A 仅在 history >= 2 时触发（指代消解需要上下文）
        if strategy == "A":
            if not history or len(history) < 2:
                return question

        cache_key = self._cache_key(question, history or [], strategy)
        cached = await cache_get(cache_key)
        if cached:
            logger.debug("Query rewrite cache hit (strategy=%s)", strategy)
            return cached.decode() if isinstance(cached, bytes) else cached

        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in (history or [])
        ) if history else "（无对话历史）"

        prompt = STRATEGY_PROMPTS[strategy].format(
            history_text=history_text,
            question=question,
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=settings.QUERY_REWRITE_MAX_TOKENS,
            )
            rewritten = response.choices[0].message.content or question
            rewritten = rewritten.strip()

            await cache_set(cache_key, rewritten, ttl=settings.QUERY_REWRITE_CACHE_TTL)
            logger.debug(
                "Query rewrite (strategy=%s): '%s' → '%s'",
                strategy, question[:60], rewritten[:60],
            )
            return rewritten

        except Exception as e:
            logger.warning("Query rewrite failed (strategy=%s), using original: %s", strategy, str(e))
            return question


# 模块级单例
query_rewrite_service = QueryRewriteService()
