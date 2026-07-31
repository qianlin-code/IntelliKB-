"""
Pre-download reranker model to local directory for offline use.

Usage:
    python scripts/download_reranker.py                          # 默认下载中文 bge-reranker-base
    python scripts/download_reranker.py --model BAAI/bge-reranker-base
    python scripts/download_reranker.py --model cross-encoder/ms-marco-MiniLM-L-6-v2
    python scripts/download_reranker.py --all                     # 下载全部三层模型

This downloads from huggingface.co and saves to RERANK_LOCAL_DIR.
After download, validates the model is loadable.

Hardware: bge-reranker-base ~1.3GB, 6GB VRAM recommended.
          ms-marco-MiniLM ~200MB, CPU-friendly.
"""
import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("download_reranker")


def download_and_validate(model_name: str, model_dir: Path) -> bool:
    """下载单个模型并验证，返回是否成功"""
    safe_name = model_name.replace("/", "_")
    model_dir_full = model_dir / safe_name
    model_dir_full.mkdir(parents=True, exist_ok=True)

    if (model_dir_full / "config.json").exists():
        logger.info("Model already exists: %s → %s", model_name, model_dir_full)
    else:
        logger.info("Downloading %s → %s ...", model_name, model_dir_full)
        from sentence_transformers import CrossEncoder
        try:
            model = CrossEncoder(model_name)
            model.save(str(model_dir_full))
            logger.info("Saved to: %s", model_dir_full)
        except Exception as e:
            logger.error("Download failed: %s", e)
            return False

    # 验证
    logger.info("Validating %s...", model_name)
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(str(model_dir_full))
        scores = model.predict([("测试问题", "测试文档")])
        logger.info("Validation OK — predict score: %s", scores[0])
        return True
    except Exception as e:
        logger.error("Validation failed for %s: %s", model_name, e)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Pre-download reranker models for offline use (Phase 8)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/download_reranker.py                     # Chinese model only\n"
            "  python scripts/download_reranker.py --all               # All three tiers\n"
            "  python scripts/download_reranker.py --model cross-encoder/ms-marco-MiniLM-L-6-v2\n"
        ),
    )
    parser.add_argument(
        "--model",
        default=settings.RERANK_MODEL_ZH,
        help=f"Model name on huggingface.co (default: {settings.RERANK_MODEL_ZH})",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Download all three tier models (zh primary + en fallback + legacy)",
    )
    args = parser.parse_args()

    local_dir = Path(settings.RERANK_LOCAL_DIR)

    if args.all:
        models_to_download = [
            settings.RERANK_MODEL_ZH,
            settings.RERANK_MODEL_FALLBACK,
            settings.RERANK_MODEL,
        ]
        # Deduplicate while preserving order
        seen = set()
        models_to_download = [m for m in models_to_download if not (m in seen or seen.add(m))]
        logger.info("Downloading all %d tier models...", len(models_to_download))
        failed = []
        for mn in models_to_download:
            ok = download_and_validate(mn, local_dir)
            if not ok:
                failed.append(mn)
        if failed:
            logger.error("%d models failed: %s", len(failed), ", ".join(failed))
            sys.exit(1)
        logger.info("All %d models downloaded successfully.", len(models_to_download))
    else:
        ok = download_and_validate(args.model, local_dir)
        if not ok:
            sys.exit(1)

    logger.info("Done. Models cached at: %s", local_dir)
    logger.info("No .env changes needed if RERANK_LOCAL_DIR is default (reranker_models/).")


if __name__ == "__main__":
    main()