"""
文档 Pydantic Schemas
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DocumentUploadResponse(BaseModel):
    doc_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    message: str


class ChunkResponse(BaseModel):
    id: int
    chunk_index: int
    content: str
    token_count: int
    model_config = ConfigDict(from_attributes=True)
