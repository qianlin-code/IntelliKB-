"""
RAG 问答 Pydantic Schemas
"""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    chunk_id: int
    document_id: int        # M4: 检索结果所属文档 ID
    content: str
    score: float
    # Phase 8: 引用增强
    chunk_index: int | None = None           # chunk 在文档中的序号
    document_title: str | None = None        # 文档标题/文件名
    highlight_text: str | None = None        # chunk 中与问题相关的句子


class SearchResponse(BaseModel):
    results: list[SearchResult]


class AskRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: int | None = Field(default=None, description="关联对话 ID，传入后将保存问答消息")


class AskStreamRequest(BaseModel):
    """Phase P0: SSE 流式问答 POST body"""
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: int | None = Field(default=None, description="关联对话 ID，传入后将保存问答消息")


class AskResponse(BaseModel):
    answer: str
    sources: list[SearchResult]
    llm_error: bool = False    # S4: LLM 调用失败时为 True


# ── Phase 2: 混合检索 ──

class HybridSearchRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    use_rerank: bool = True
    # M5 history 格式: [{"role":"user","content":"..."}, {"role":"assistant",...}, {"role":"user",...}]
    history: list[dict] | None = None


class HybridSearchResponse(BaseModel):
    results: list[SearchResult]
    rewritten_query: str | None = None
