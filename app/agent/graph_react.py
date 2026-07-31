"""
完整 ReAct 循环 Agent Graph（Phase 5 P2）

与 graph.py 的关系：
- graph.py: 简化两阶段 call_tool → call_model → end（REACT_ENABLED=False）
- graph_react.py: ReAct 循环 call_model ↔ call_tool → end（REACT_ENABLED=True）

共用 AgentState、_lc_message_to_dict。

技术路线：裸 OpenAI client + 手动构建 tool message dict。
LangGraph 的 add_messages reducer 接受 dict 格式的消息
（{"role": "tool", "content": "...", "tool_call_id": "..."}），
与 Phase 3/4 的 graph.py 保持一致。
"""
import json
import logging
from typing import Literal

from langchain_core.messages import SystemMessage
from langgraph.graph import END, StateGraph

from app.agent.graph import AgentState, _lc_message_to_dict

logger = logging.getLogger("app")

SYSTEM_PROMPT_REACT = (
    "你是一个智能知识库助手，基于 IntelliKB 平台为用户提供问答服务。\n\n"
    "【工具使用】\n"
    "你需要自主决定使用哪些工具以及调用顺序。\n"
    "可用的工具：\n"
    "- retrieve_knowledge: 检索知识库中的相关文档片段\n"
    "- get_knowledge_base_info: 获取当前知识库的统计信息\n\n"
    "【回答规则】\n"
    "1. 优先使用工具获取信息后再回答\n"
    "2. 基于检索结果回答，用 [source:N] 格式标注信息来源（N 为来源编号）\n"
    "3. 如果检索结果不足以回答，请明确说明\n"
    "4. 用中文回答，保持专业友好\n"
    "5. 不需要反复检索同一问题，获取足够信息后直接回答"
)


def create_react_graph(llm_client, tools: list, model_name: str, max_iterations: int = 5):
    """创建 ReAct 循环 Agent Graph

    流程: call_model → [tool_call?] → call_tool → call_model → ... → end
    """
    tool_map = {t.name: t for t in tools}

    async def call_model(state: AgentState) -> dict:
        """LLM 节点：决定调用工具或直接回答"""
        messages = list(state.get("messages", []))

        first_msg = messages[0] if messages else None
        if not isinstance(first_msg, SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT_REACT)] + messages

        api_messages = [_lc_message_to_dict(m) for m in messages]

        tool_definitions = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": (
                        t.args_schema.schema()
                        if hasattr(t, "args_schema") and t.args_schema is not None
                        else {"type": "object", "properties": {}}
                    ),
                },
            }
            for t in tools
        ]

        response = await llm_client.chat.completions.create(
            model=model_name,
            messages=api_messages,
            temperature=0.3,
            max_tokens=2048,
            tools=tool_definitions if tool_definitions else None,
            tool_choice="auto" if tool_definitions else None,
        )

        choice = response.choices[0]
        msg = choice.message

        # Phase 7: 提取并累加 token 用量（ReAct 可能多次调用 LLM）
        current_usage = None
        if hasattr(response, 'usage') and response.usage:
            current_usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
            }
        prev_usage = state.get("llm_usage", {})
        llm_usage = None
        if current_usage or prev_usage:
            llm_usage = {
                "prompt_tokens": prev_usage.get("prompt_tokens", 0) + (current_usage or {}).get("prompt_tokens", 0),
                "completion_tokens": prev_usage.get("completion_tokens", 0) + (current_usage or {}).get("completion_tokens", 0),
            }

        if msg.tool_calls:
            return {
                "messages": [{
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }],
                "sources": state.get("sources", []),
                "tool_calls_log": state.get("tool_calls_log", []),
                "llm_usage": llm_usage,
            }
        else:
            return {
                "messages": [{"role": "assistant", "content": msg.content or ""}],
                "sources": state.get("sources", []),
                "tool_calls_log": state.get("tool_calls_log", []),
                "llm_usage": llm_usage,
            }

    async def call_tool(state: AgentState) -> dict:
        """工具执行节点：执行所有 pending tool_calls

        Phase 6 修复：LangChain AIMessage.tool_calls 返回 dict 列表（非 ToolCall 对象）。
        使用 dict.get() 访问 name/args/id。
        """
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else {}

        tool_calls = []
        if isinstance(last_msg, dict):
            tool_calls = last_msg.get("tool_calls", [])
        elif hasattr(last_msg, "tool_calls"):
            for tc in (last_msg.tool_calls or []):
                if isinstance(tc, dict):
                    tool_calls.append({
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {})),
                        },
                    })
                else:
                    tool_calls.append({
                        "id": getattr(tc, "id", ""),
                        "type": "function",
                        "function": {
                            "name": getattr(tc, "name", ""),
                            "arguments": json.dumps(getattr(tc, "args", {})),
                        },
                    })

        new_messages = []
        new_log = list(state.get("tool_calls_log", []))
        sources = list(state.get("sources", []))

        for tc in tool_calls:
            func_info = tc.get("function", {})
            name = func_info.get("name", "")
            args_str = func_info.get("arguments", "{}")
            tc_id = tc.get("id", "")

            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            tool_fn = tool_map.get(name)
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(args)
                    output_str = json.dumps(result, ensure_ascii=False, default=str)
                    new_log.append({
                        "tool": name,
                        "input": args,
                        "output": output_str[:200],
                    })
                    if name == "retrieve_knowledge":
                        for item in (result if isinstance(result, list) else []):
                            if isinstance(item, dict) and "chunk_id" in item:
                                sources.append(item)
                    new_messages.append({
                        "role": "tool",
                        "content": output_str[:4000],
                        "tool_call_id": tc_id,
                    })
                except Exception as e:
                    new_messages.append({
                        "role": "tool",
                        "content": f"工具执行失败: {str(e)}",
                        "tool_call_id": tc_id,
                    })
            else:
                new_messages.append({
                    "role": "tool",
                    "content": f"未知工具: {name}",
                    "tool_call_id": tc_id,
                })

        return {
            "messages": new_messages,
            "sources": sources,
            "tool_calls_log": new_log,
        }

    def should_continue(state: AgentState) -> Literal["call_tool", "__end__"]:
        """路由：检查最后一条消息是否包含 tool_calls

        Phase 6 修复：LangGraph reducer 将 dict 消息转为 LangChain message 对象，
        AIMessage 的 tool_calls 通过属性访问，非 .get()。
        """
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else {}
        # 兼容 dict 和 LangChain AIMessage 两种格式
        if isinstance(last_msg, dict):
            tool_calls = last_msg.get("tool_calls", [])
        elif hasattr(last_msg, "tool_calls"):
            tool_calls = last_msg.tool_calls or []
        else:
            tool_calls = []
        if tool_calls:
            return "call_tool"
        return "__end__"

    # ── 构建图 ──
    workflow = StateGraph(AgentState)
    workflow.add_node("call_model", call_model)
    workflow.add_node("call_tool", call_tool)

    workflow.set_entry_point("call_model")
    workflow.add_conditional_edges("call_model", should_continue, {
        "call_tool": "call_tool",
        "__end__": END,
    })
    workflow.add_edge("call_tool", "call_model")

    return workflow
