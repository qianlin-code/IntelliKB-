"""
Phase 8: 答案引用解析

从 LLM 回答中解析 [source:N] 格式的引用标记，
映射到对应的 source 元数据。
"""
import re
import logging

logger = logging.getLogger("app")

# 匹配 [source:N] 或 [来源 N] 或 [来源N] 格式
_CITATION_PATTERN = re.compile(r'\[source:\s*(\d+)\]|\[来源\s*(\d+)\]', re.IGNORECASE)


def parse_citations(answer: str) -> list[int]:
    """从 answer 中提取所有引用的 source 编号。

    Returns:
        去重排序的 source 编号列表（从 1 开始）。
    """
    indices: set[int] = set()
    for match in _CITATION_PATTERN.finditer(answer):
        n = int(match.group(1) or match.group(2))
        if 1 <= n <= 50:  # 合理的上限
            indices.add(n)
    return sorted(indices)


def build_citation_info(
    source_indices: list[int],
    sources: list[dict],
) -> list[dict]:
    """根据 source 编号列表，构建 CitationInfo 列表。

    Args:
        source_indices: parse_citations() 返回的编号列表
        sources: 检索返回的 source dict 列表

    Returns:
        [{"source_index": N, "chunk_id": X, "document_id": Y, "excerpt": "..."}, ...]
    """
    result = []
    for idx in source_indices:
        if 1 <= idx <= len(sources):
            src = sources[idx - 1]
            excerpt = src.get("content", "")[:200] if src.get("content") else ""
            result.append({
                "source_index": idx,
                "chunk_id": src.get("chunk_id", 0),
                "document_id": src.get("document_id", 0),
                "excerpt": excerpt,
            })
    return result
