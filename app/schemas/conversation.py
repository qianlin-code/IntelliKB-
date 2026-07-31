"""
对话 Schemas
"""
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    kb_id: int
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_pinned: bool | None = None
    is_starred: bool | None = None


class ConversationResponse(BaseModel):
    id: int
    kb_id: int
    user_id: int
    title: str | None = None
    message_count: int = 0
    is_pinned: bool = False
    is_starred: bool = False
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int
