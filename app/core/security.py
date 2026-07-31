"""
安全模块 —— JWT (PyJWT) + bcrypt 密码哈希 + API Key 生成
"""
import asyncio
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
import jwt  # PyJWT

from app.config import settings
from app.core.time_utils import utcnow


# ── bcrypt 哈希 ──

def hash_secret(plain: str) -> str:
    """bcrypt 哈希（自动生成随机盐），用于密码和 API Key"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_secret(plain: str, hashed: str) -> bool:
    """恒定时间对比（防时序攻击）"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


async def verify_secret_async(plain: str, hashed: str) -> bool:
    """异步验证 —— offload bcrypt 到线程池，避免阻塞事件循环"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, bcrypt.checkpw, plain.encode(), hashed.encode()
    )


# ── JWT (PyJWT) ──

def create_access_token(user_id: int, username: str) -> str:
    """生成 access token（短期）"""
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(user_id: int, username: str) -> str:
    """生成 refresh token（长期）"""
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    """
    解码 JWT — 强制校验必填字段 sub / exp / type / jti。

    PyJWT 的 jwt.decode 自动验证签名 + exp，
    这里在 decode 之后做二次校验确保业务必填字段存在。
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    if "type" not in payload:
        raise jwt.InvalidTokenError("Token 缺少 'type' 字段")
    if "jti" not in payload:
        raise jwt.InvalidTokenError("Token 缺少 'jti' 字段")
    return payload


# ── API Key 生成 ──

def generate_api_key() -> tuple[str, str, str, datetime]:
    """
    生成 API Key，返回 (原始值, bcrypt哈希, 前缀, 过期时间)。

    API Key 格式固化：
      raw = "sk-intellikb-" + secrets.token_urlsafe(32)
      prefix = raw[:12]  → "sk-intellikb"  供 UI 展示
      hash = bcrypt(raw) → bcrypt $2b$12$...

    原始值仅在生成时返回一次，前端必须提示用户立即保存。
    """
    raw = "sk-intellikb-" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    hashed = hash_secret(raw)
    expires_at = utcnow() + timedelta(days=365)
    return raw, hashed, prefix, expires_at
