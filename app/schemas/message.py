"""
消息 Schemas
"""
from pydantic import BaseModel


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    metadata_json: dict | None = None
    token_count: int = 0
    tool_call_id: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    has_more: bool
