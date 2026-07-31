"""
Agent Graph 公共节点（Phase 5）

抽取 call_tool 节点逻辑，供 graph.py 引用。

注意：AgentState 通过 TYPE_CHECKING 导入避免循环引用
（graph.py 同时 import nodes.py）。
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.graph import AgentState

logger = logging.getLogger("app")


def create_call_tool_node(tool_map: dict):
    """创建 call_tool 节点（闭包注入 tool_map）

    供 graph.py 的 StateGraph.add_node("call_tool", ...) 使用。
    """

    async def call_tool(state: AgentState) -> dict:
        """检索知识库"""
        messages = state.get("messages", [])
        if not messages:
            return {"messages": [], "sources": [], "tool_calls_log": []}

        # 获取最后一条 user 消息
        last_user_msg = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break
            elif hasattr(m, "type") and m.type == "human":
                last_user_msg = m.content
                break

        if not last_user_msg:
            return {
                "messages": [],
                "sources": state.get("sources", []),
                "tool_calls_log": state.get("tool_calls_log", []),
            }

        retrieve_fn = tool_map.get("retrieve_knowledge")
        if retrieve_fn is None:
            logger.error("retrieve_knowledge not found in tool_map: %s", list(tool_map.keys()))
            return {
                "messages": [{"role": "tool", "content": "检索工具不可用", "tool_call_id": "fallback"}],
                "sources": state.get("sources", []),
                "tool_calls_log": state.get("tool_calls_log", []),
            }

        sources = list(state.get("sources", []))
        new_log = list(state.get("tool_calls_log", []))

        try:
            result = await retrieve_fn.ainvoke({"question": last_user_msg, "top_k": 5})
            output_str = json.dumps(result, ensure_ascii=False, default=str)
            new_log.append({
                "tool": "retrieve_knowledge",
                "input": {"question": last_user_msg[:100]},
                "output": output_str[:200],
            })

            for item in (result if isinstance(result, list) else []):
                if isinstance(item, dict) and "chunk_id" in item:
                    sources.append(item)

            tool_msg = {
                "role": "tool",
                "content": output_str[:4000],
                "tool_call_id": "retrieve_knowledge",
            }
            return {
                "messages": [tool_msg],
                "sources": sources,
                "tool_calls_log": new_log,
            }
        except Exception as e:
            logger.exception("retrieve_knowledge failed")
            return {
                "messages": [{
                    "role": "tool",
                    "content": f"检索失败: {str(e)}",
                    "tool_call_id": "retrieve_knowledge",
                }],
                "sources": sources,
                "tool_calls_log": new_log,
            }

    return call_tool
