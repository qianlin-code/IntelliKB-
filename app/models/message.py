"""
消息模型 —— 每条消息属于一个对话

硬删除设计：
- Message 不支持软删除（ConversationService.delete() 先硬删除所有 Message）
- tool_call_id 用于关联 tool_call 和 tool_result 消息
"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    """消息（硬删除）"""
    __tablename__ = "sys_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="对话 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="角色: user/assistant/system/tool_call/tool_result")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="元数据 JSON（工具调用参数、引用来源等）"
    )
    token_count: Mapped[int] = mapped_column(Integer, default=0, comment="token 估算数")
    tool_call_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="工具调用 ID（对应 LLM response 中的 tool_call_id）"
    )
