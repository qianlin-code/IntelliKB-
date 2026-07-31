"""
知识库成员 Pydantic Schemas
"""
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class MemberAdd(BaseModel):
    user_id: int
    role: str = Field(default="viewer", pattern="^(editor|viewer)$")


class MemberUpdate(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")


class MemberResponse(BaseModel):
    user_id: int
    username: str = ""
    role: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
