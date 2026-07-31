"""
LangGraph StateGraph 定义 —— Agent ReAct 循环

Phase 3 简化策略：
- 不依赖 LLM 的 function calling（qwen2.5:7b 支持不稳定）
- 硬编码两阶段流程：search → generate → end
- 节点流程: call_tool → call_model → end

Phase 4 升级为完整 ReAct（call_model → should_continue → call_tool 循环）

Phase 5: call_tool 节点逻辑抽取到 nodes.py，增加 max_iterations 签名参数。
"""
import json
import logging
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired

from app.agent.nodes import create_call_tool_node

logger = logging.getLogger("app")


class AgentState(TypedDict):
    """LangGraph 状态"""
    messages: Annotated[list, add_messages]
    kb_id: int
    user_id: int
    sources: list[dict]
    tool_calls_log: list[dict]
    # Phase 7: 可选 LLM usage（{"prompt_tokens": int, "completion_tokens": int}）
    llm_usage: NotRequired[dict]


def _lc_message_to_dict(msg) -> dict:
    """将 LangChain message 对象转换为 OpenAI API 兼容 dict"""
    msg_type = type(msg).__name__

    if msg_type == "SystemMessage":
        return {"role": "system", "content": msg.content}
    elif msg_type == "HumanMessage":
        return {"role": "user", "content": msg.content}
    elif msg_type == "AIMessage":
        d = {"role": "assistant", "content": msg.content or ""}
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
                        "arguments": (
                            json.dumps(tc.get("args", {})) if isinstance(tc, dict)
                            else json.dumps(getattr(tc, "args", {}))
                        ),
                    },
                }
                for tc in msg.tool_calls
            ]
        return d
    elif msg_type == "ToolMessage":
        return {
            "role": "tool",
            "content": msg.content or "",
            "tool_call_id": getattr(msg, "tool_call_id", ""),
        }
    else:
        if isinstance(msg, dict):
            return msg
        return {"role": "user", "content": str(msg)}


def create_agent_graph(llm_client, tools: list, model_name: str, max_iterations: int = 5):
    """
    Phase 3 简化 Graph：search → generate → end

    硬编码流程：
    1. call_tool: 始终调用 retrieve_knowledge 检索知识库
    2. call_model: 基于检索结果 + 对话历史生成回答
    3. end

    不依赖 LLM function calling，对 qwen2.5:7b 更稳定。

    Phase 4: 返回未编译的 StateGraph，由 AgentService._get_graph() 负责 compile(checkpointer=...)。

    Phase 5: max_iterations 参数与 create_react_graph 签名对齐（简化两阶段不使用）。
             call_tool 节点调用 nodes.create_call_tool_node() 公共实现。
    """
    tool_map = {t.name: t for t in tools}
    logger.info("Agent graph created (Phase 3 simplified mode): %d tools, model=%s",
                len(tools), model_name)

    SYSTEM_PROMPT = (
        "你是 IntelliKB 智能知识库助手。你只拥有【检索结果】中的信息，必须基于这些信息回答用户问题。\n\n"
        "【回答示例】\n"
        "示例 1：\n"
        "检索结果：[来源 1] 文档#81：IntelliKB 使用 Chroma 作为向量数据库，Ollama 作为本地大模型。\n"
        "用户问题：IntelliKB 使用什么向量数据库？\n"
        "回答：IntelliKB 使用 Chroma 作为向量数据库。[source:1]\n\n"
        "示例 2：\n"
        "检索结果：[来源 1] 文档#81：IntelliKB 使用 Chroma 作为向量数据库，Ollama 作为本地大模型。\n"
        "用户问题：你是什么模型？\n"
        "回答：根据当前知识库内容无法回答该问题。\n\n"
        "【强制规则】\n"
        "1. 直接回答用户问题，禁止说问候语（如“您好”、“请问”）、禁止反问用户、禁止请求用户提供更多信息。\n"
        "2. 如果【检索结果】中包含与用户问题相关的事实，请直接给出答案，并在相关处用 [source:N] 标注来源。\n"
        "3. 如果【检索结果】与用户问题完全无关，只回答：“根据当前知识库内容无法回答该问题。”\n"
        "4. 禁止根据模型自身知识或常识回答。禁止复述检索结果中与问题无关的内容。\n"
        "5. 用中文回答，简洁专业。"
    )

    call_tool = create_call_tool_node(tool_map)  # Phase 5: 引用 nodes.py 公共节点

    def _format_retrieved_context(raw_context: str) -> str:
        """将 tool 返回的 JSON 检索结果格式化为模型易读的文本。"""
        if not raw_context.strip():
            return ""
        try:
            data = json.loads(raw_context)
        except json.JSONDecodeError:
            return raw_context

        if not isinstance(data, list) or not data:
            return str(data)

        lines = []
        for idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            content = item.get("content", "")
            doc_id = item.get("document_id", "")
            if not content:
                continue
            lines.append(f"[来源 {idx}] 文档#{doc_id}：{content.strip()}")
        return "\n".join(lines) if lines else str(data)

    async def call_model(state: AgentState) -> dict:
        """Step 2: 基于检索结果生成回答（使用 RAG 式 prompt，不携带历史对话）"""
        raw_messages = list(state.get("messages", []))

        from langchain_core.messages import SystemMessage, HumanMessage

        # 分离检索结果（tool 消息）与当前用户问题
        retrieved_context = ""
        current_question = ""
        for m in raw_messages:
            if isinstance(m, dict) and m.get("role") == "tool":
                retrieved_context += f"\n{m.get('content', '')}"
            elif hasattr(m, "type") and m.type == "tool":
                retrieved_context += f"\n{getattr(m, 'content', '')}"
            elif isinstance(m, dict) and m.get("role") == "user":
                current_question = m.get("content", "")
            elif type(m).__name__ == "HumanMessage":
                current_question = getattr(m, "content", "")

        # 使用与 RAG 服务完全一致的上下文格式，小模型对这种分隔更敏感
        raw_sources = []
        try:
            raw_sources = json.loads(retrieved_context) if retrieved_context.strip() else []
        except json.JSONDecodeError:
            pass

        context_parts = []
        for idx, src in enumerate(raw_sources, start=1):
            if not isinstance(src, dict):
                continue
            content = src.get("content", "")
            doc_id = src.get("document_id", "")
            title = f" (文档:{doc_id})" if doc_id else ""
            context_parts.append(f"[来源 {idx}]{title}\n{content.strip()}")
        context = "\n\n---\n\n".join(context_parts)

        rag_prompt = f"""参考资料：
{context}

用户问题：{current_question}

请用中文回答。如果参考资料不足以回答问题，请明确说明。
重要：回答时使用 [source:N] 格式标注引用来源（N 为来源编号）。"""

        messages_for_llm = [
            SystemMessage(content=(
                "你是一个智能知识库助手。请根据参考资料回答用户问题。"
                "用中文回答。如果参考资料不足以回答问题，请明确说明。"
                "回答时引用来源编号。"
            )),
            HumanMessage(content=rag_prompt),
        ]

        api_messages = [_lc_message_to_dict(m) for m in messages_for_llm]

        response = await llm_client.chat.completions.create(
            model=model_name,
            messages=api_messages,
            temperature=0.3,
            max_tokens=2048,
        )

        choice = response.choices[0]
        msg_content = choice.message.content or ""

        # Phase 7: 提取真实 token 用量（若 provider 返回）
        llm_usage = None
        if hasattr(response, 'usage') and response.usage:
            llm_usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
            }

        return {
            "messages": [{"role": "assistant", "content": msg_content}],
            "sources": state.get("sources", []),
            "tool_calls_log": state.get("tool_calls_log", []),
            "llm_usage": llm_usage,
        }

    # ── 构建图 ──
    workflow = StateGraph(AgentState)

    workflow.add_node("call_tool", call_tool)
    workflow.add_node("call_model", call_model)

    workflow.set_entry_point("call_tool")
    workflow.add_edge("call_tool", "call_model")
    workflow.add_edge("call_model", END)

    return workflow  # Phase 4: 返回未编译的 StateGraph，由调用方 compile()
