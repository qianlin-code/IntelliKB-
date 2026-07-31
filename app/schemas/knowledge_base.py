"""
知识库 Pydantic Schemas
"""
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = False
    chunk_size: int = Field(default=500, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=500)


class KBUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_public: bool | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)


class KBResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None
    is_public: bool
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentConfigUpdate(BaseModel):
    """Phase 9: Agent 人设配置"""
    system_prompt: str | None = Field(default=None, max_length=2000)
    agent_enabled: bool | None = None


class KBStats(BaseModel):
    kb_id: int
    document_count: int
    chunk_count: int
    total_size_bytes: int
