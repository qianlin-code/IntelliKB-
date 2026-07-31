"""
Agent 对话 Schemas
"""
from pydantic import BaseModel, Field

from app.schemas.qa import SearchResult


class AgentChatRequest(BaseModel):
    conversation_id: int | None = None  # None 表示新建对话
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    stream: bool = False


class AgentChatStreamRequest(BaseModel):
    """Phase P0: Agent SSE 流式对话 POST body"""
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class ToolCallInfo(BaseModel):
    tool: str
    input: dict
    output: str


class CitationInfo(BaseModel):
    """Phase 8: 答案中的引用标注"""
    source_index: int           # 对应 [source:N] 中的 N（从 1 开始）
    chunk_id: int               # 被引用的 chunk ID
    document_id: int            # 被引用的文档 ID
    excerpt: str = ""           # 引用内容的摘要


class AgentChatResponse(BaseModel):
    conversation_id: int
    answer: str
    sources: list[SearchResult] = []
    tool_calls: list[ToolCallInfo] = []
    token_count: int = 0
    fallback: bool = False  # Phase 6: 是否触发云端→本地降级
    # Phase 8: 引用标注
    citations: list[CitationInfo] = []
    # Phase 8 P1.3: 推荐问题
    follow_up_questions: list[str] = []


class AgentSSEEvent(BaseModel):
    """SSE 各事件类型的数据结构"""
    event: str  # thought / tool_call / tool_result / sources / token / done
    data: dict
