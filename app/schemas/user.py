"""
用户相关 Pydantic Schema
"""
from datetime import datetime

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    email: str | None = Field(None, max_length=100, description="邮箱")


class UserLogin(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh Token")
    current_access_token: str | None = Field(None, description="待撤销的 Access Token（可选）")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    username: str
    email: str | None
    is_active: bool
    system_role: str = "user"
    api_key_enabled: bool
    api_key_prefix: str | None
    api_key_expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyResponse(BaseModel):
    api_key: str
    prefix: str
    expires_at: datetime


class APIKeyInfoResponse(BaseModel):
    prefix: str | None
    expires_at: str | None
    last_used_at: str | None
    enabled: bool
