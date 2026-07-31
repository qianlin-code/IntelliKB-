"""
Cross-encoder Rerank 服务

Phase 8: 三层加载策略
  1. RERANK_MODEL_ZH（中文优化，bge-reranker-base）— 优先
  2. RERANK_MODEL_FALLBACK（英文通用，ms-marco-MiniLM）— 降级
  3. 禁用 reranker，返回原始排序 — 最终降级
"""
import asyncio
import logging

from app.config import settings

logger = logging.getLogger("app")

# Phase 8: 中文优化模型关键词，用于自动识别
_ZH_MODEL_KEYWORDS = ("bge", "zh", "chinese", "cn", "multilingual", "bce")


class RerankService:
    """Cross-encoder Rerank

    Phase 8 三层加载策略:
      1. 优先加载 RERANK_MODEL_ZH（中文优化，默认 bge-reranker-base）
      2. 加载失败 → 回退 RERANK_MODEL_FALLBACK（英文通用，ms-marco-MiniLM）
      3. 再失败 → 禁用 reranker，返回原始排序

    每层都先检查本地缓存目录，再尝试网络下载。
    """

    def __init__(self):
        self._model = None
        self._model_available = True  # 跟踪模型加载是否成功
        self._model_name = None       # 当前加载的模型名（日志用）

    @property
    def model(self):
        if self._model is None and self._model_available:
            # Phase 8: 按优先级尝试加载三个模型
            self._model = self._try_load_model(
                settings.RERANK_MODEL_ZH, "primary (zh-optimized)"
            )
            if self._model is None:
                self._model = self._try_load_model(
                    settings.RERANK_MODEL_FALLBACK, "fallback (en-universal)"
                )
            if self._model is None:
                # Phase 7 保留: 最后尝试 RERANK_MODEL 通用配置
                self._model = self._try_load_model(
                    settings.RERANK_MODEL, "legacy (RERANK_MODEL)"
                )
            if self._model is None:
                self._model_available = False
                logger.warning(
                    "All rerank models unavailable — reranking disabled. "
                    "Run: python scripts/download_reranker.py --model %s",
                    settings.RERANK_MODEL_ZH,
                )
        return self._model

    @staticmethod
    def _is_zh_model(model_name: str) -> bool:
        """自动判断模型是否中文优化"""
        lower = model_name.lower()
        return any(kw in lower for kw in _ZH_MODEL_KEYWORDS)

    def _try_load_model(self, model_name: str, tier_label: str):
        """尝试加载一个模型，成功返回 CrossEncoder，失败返回 None。

        加载顺序: 本地缓存目录 → huggingface 下载 → 下载后缓存到本地。
        """
        from sentence_transformers import CrossEncoder
        from pathlib import Path

        local_dir = Path(settings.RERANK_LOCAL_DIR) if settings.RERANK_LOCAL_DIR else None
        safe_name = model_name.replace("/", "_")
        local_model_dir = local_dir / safe_name if local_dir else None

        # 判断模型语言特性
        is_zh = self._is_zh_model(model_name)
        lang_tag = "zh-optimized" if is_zh else "en-universal"

        # Step 1: 从本地目录加载
        if local_model_dir and local_model_dir.is_dir() and (local_model_dir / "config.json").exists():
            logger.info(
                "Rerank [%s] loading from local dir (%s): %s",
                tier_label, lang_tag, local_model_dir,
            )
            try:
                model = CrossEncoder(str(local_model_dir))
                self._model_name = model_name
                return model
            except Exception as e:
                logger.warning(
                    "Rerank [%s] local model load failed: %s", tier_label, str(e)[:120]
                )
                # 本地模型损坏，继续尝试网络下载

        # Step 2: 从 huggingface 下载
        logger.info(
            "Rerank [%s] downloading from huggingface (%s): %s",
            tier_label, lang_tag, model_name,
        )
        try:
            model = CrossEncoder(model_name)
            self._model_name = model_name
            # 下载成功后缓存到本地目录（供后续离线使用）
            if local_model_dir and not local_model_dir.exists():
                try:
                    local_model_dir.mkdir(parents=True, exist_ok=True)
                    model.save(str(local_model_dir))
                    logger.info("Rerank [%s] cached to: %s", tier_label, local_model_dir)
                except Exception:
                    pass  # 缓存失败不影响使用
            return model
        except Exception as e:
            logger.warning(
                "Rerank [%s] download failed (%s): %s",
                tier_label, model_name, str(e).split("\n")[0] if str(e) else type(e).__name__,
            )
            return None

    async def rerank(
        self, question: str, chunks: list[dict], top_k: int | None = None,
    ) -> list[dict]:
        """
        对候选 chunks 做 cross-encoder 重排序。

        chunks: [{content, chunk_id, document_id, score, ...}, ...]
        返回: 按 rerank_score 降序的前 top_k 个
        """
        if not chunks:
            return []
        if not settings.RERANK_ENABLED:
            return chunks[:top_k] if top_k else chunks

        # Phase 7: 模型不可用时直接降级，避免进入 asyncio.to_thread
        if not self._model_available:
            return chunks[:top_k] if top_k else chunks

        top_k = top_k or settings.HYBRID_RERANK_TOP_K

        pairs = [(question, c["content"]) for c in chunks]
        try:
            scores = await asyncio.to_thread(
                self.model.predict, pairs, show_progress_bar=False
            )
        except Exception as e:
            logger.warning("Rerank failed, returning original order: %s", str(e))
            # 降级：返回原始排序
            return chunks[:top_k]

        for i, c in enumerate(chunks):
            if i < len(scores):
                c["rerank_score"] = float(scores[i])

        ranked = sorted(
            chunks,
            key=lambda x: x.get("rerank_score", 0.0),
            reverse=True,
        )
        return ranked[:top_k]


# 模块级单例
rerank_service = RerankService()
