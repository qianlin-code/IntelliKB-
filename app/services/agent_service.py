"""
Agent 对话服务 —— 封装 LangGraph ReAct 对话

Phase 4 增强：
- MySQL Checkpointer 集成（中断恢复）
- 语义标题异步生成（BackgroundTasks）
- Graph 每次重新 compile（支持 CHECKPOINT_ENABLED 热切换）

Phase 6 增强：
- 成本上限保护（cost_tracker）
- 云端超时 fallback（DeepSeek → Ollama 降级）
"""
import asyncio
import json
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import openai
from openai import AsyncOpenAI
from fastapi import HTTPException

from app.agent.graph import AgentState, create_agent_graph
from app.agent.tools.retrieve_knowledge import create_retrieve_knowledge_tool
from app.agent.tools.get_kb_info import create_kb_info_tool
from app.config import settings
from app.core.llm_client import get_llm_client
from app.repositories.conversation import ConversationRepository
from app.repositories.message import MessageRepository
from app.schemas.agent import AgentChatResponse, CitationInfo, ToolCallInfo
from app.schemas.qa import SearchResult
from app.services.citation_parser import parse_citations, build_citation_info
from app.services.conversation_service import ConversationService
from app.services.kb_service import KBService

logger = logging.getLogger("app")

# 截断常数
MAX_HISTORY_ROUNDS = 20
MAX_CONTEXT_TOKENS = 8192
# Phase 8: 指代词模式（检测多轮对话中的指代依赖）
_REFERENCE_PATTERNS = [
    "刚才", "刚刚", "之前", "上文", "前面", "上面", "那个", "这个",
    "它", "他", "她", "他们", "她们", "它们",
    "再说说", "再讲讲", "详细说说", "继续", "还有呢",
]
# Phase 8: 推荐问题 prompt
FOLLOW_UP_PROMPT = (
    "根据以下对话，生成 3 个用户可以继续追问的相关问题。\n"
    "要求：\n"
    "1. 每个问题应独立且可在当前知识库中检索到答案\n"
    "2. 问题应简短（不超过 25 字）\n"
    "3. 每行一个问题，不要编号\n"
    "4. 用中文\n\n"
    "用户问题：{question}\n"
    "助手回答：{answer}\n\n"
    "推荐问题："
)

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

# Phase 6: 云端 LLM 异常类型——捕获后自动 fallback 到本地 Ollama
_CLOUD_FALLBACK_EXCEPTIONS = (
    asyncio.TimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.APITimeoutError,
)


@dataclass
class _StreamContext:
    """流式对话共享上下文，承载三条路径的公共状态与依赖。"""

    conv_id: int
    is_new_conversation: bool
    question: str
    all_messages: list[dict]
    initial_state: AgentState
    config: dict
    checkpointer: Any | None
    msg_repo: MessageRepository
    conv_service: ConversationService
    tools: list
    collected_answer: str = ""
    all_sources: list[dict] = field(default_factory=list)
    all_tool_calls: list[dict] = field(default_factory=list)
    llm_usage: dict | None = None

    def reset_for_fallback(self) -> None:
        """触发 cloud fallback 后重置收集状态，避免残留。"""
        self.collected_answer = ""
        self.all_sources = []
        self.all_tool_calls = []
        self.llm_usage = None


class AgentService:
    """Agent 对话服务"""

    def __init__(self, db):
        self.db = db
        self.llm_client, self.llm_model = get_llm_client(purpose="agent")
        self.kb_id: int | None = None
        self.user_id: int | None = None
        self._fallback_triggered = False  # Phase 6: fallback 标识

    # ── Phase 6: 成本上限 + fallback ──

    async def _check_cost_limits(self):
        """调用云端 LLM 前检查成本上限。超限抛 HTTPException 429。"""
        if settings.LLM_PROVIDER == "ollama":
            return
        from app.core.cost_tracker import check_limits
        exceeded, reason = await check_limits()
        if exceeded:
            raise HTTPException(status_code=429, detail={
                "code": "TOKEN_LIMIT_EXCEEDED",
                "message": reason,
            })

    async def _record_cost(self, input_tokens: int, output_tokens: int):
        """LLM 调用后记录 token 消耗（云端 provider 才记录）。"""
        if settings.LLM_PROVIDER == "ollama":
            return
        from app.core.cost_tracker import record_usage
        await record_usage(input_tokens, output_tokens)

    async def _try_cloud_fallback(self) -> tuple:
        """尝试获取本地 Ollama fallback 客户端。

        返回 (llm_client, model_name, is_fallback)。
        若当前已是 ollama 则直接返回，不做切换。

        Phase 6 bugfix: 使用独立的 OLLAMA_BASE_URL / OLLAMA_API_KEY
        构造 fallback 客户端，不再复用 settings.LLM_BASE_URL / settings.LLM_API_KEY
        （这两个值在 LLM_PROVIDER=deepseek 时指向云端地址，导致 fallback 不生效）。
        """
        if settings.LLM_PROVIDER == "ollama":
            return self.llm_client, self.llm_model, False

        try:
            fallback_client = AsyncOpenAI(
                base_url=settings.OLLAMA_BASE_URL.rstrip("/"),
                api_key=settings.OLLAMA_API_KEY,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=1,
            )
            logger.warning(
                "Cloud fallback triggered: original=%s → ollama base_url=%s model=%s trace_id=%s",
                settings.LLM_PROVIDER,
                settings.OLLAMA_BASE_URL,
                settings.AGENT_MODEL,
                getattr(self, '_trace_id', 'N/A'),
            )
            self._fallback_triggered = True
            return fallback_client, settings.AGENT_MODEL, True
        except Exception:
            return self.llm_client, self.llm_model, False

    # ── 工具构建（闭包注入 db）──

    def _build_tools(self):
        """通过闭包将 db session 注入到工具函数中。

        简化策略（Phase 3）：只注册 retrieve_knowledge。
        get_knowledge_base_info 保留但暂不注册，避免小模型工具选择不稳定。
        """
        db = self.db
        kb_id = self.kb_id
        user_id = self.user_id

        retrieve_tool = create_retrieve_knowledge_tool(db, kb_id, user_id)

        tools = [retrieve_tool]
        if settings.REACT_ENABLED:
            kb_info_tool = create_kb_info_tool(db, kb_id, user_id)
            tools.append(kb_info_tool)
        return tools

    def _get_graph(self, checkpointer=None):
        """获取编译后的 LangGraph —— 每次调用重新 compile，禁止缓存

        Phase 4 关键约束：每次调用 graph.compile(checkpointer=checkpointer)，
        确保 CHECKPOINT_ENABLED 开关实时生效，不会因缓存导致切回 MemorySaver 失败。

        Phase 5: 根据 REACT_ENABLED 选择 graph 实现。
        """
        tools = self._build_tools()

        if settings.REACT_ENABLED:
            from app.agent.graph_react import create_react_graph
            graph = create_react_graph(
                llm_client=self.llm_client,
                tools=tools,
                model_name=self.llm_model,
                max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
            )
        else:
            graph = create_agent_graph(
                llm_client=self.llm_client,
                tools=tools,
                model_name=self.llm_model,
                max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
            )
        return graph.compile(checkpointer=checkpointer)

    # ── 历史截断 ──

    @staticmethod
    def _has_reference_words(question: str) -> bool:
        """Phase 8: 检测问题中是否包含指代词（多轮依赖信号）。"""
        return any(pat in question for pat in _REFERENCE_PATTERNS)

    @staticmethod
    def _summarize_last_rounds(messages: list[dict], rounds: int = 2) -> str:
        """Phase 8: 生成最近 N 轮的简短摘要（50 字以内）。

        不依赖 LLM，使用启发式截取：
        - 提取最后 N 个 user→assistant 问答对
        - 截取每段内容的前 50 字符合并
        """
        if not messages:
            return ""
        non_system = [m for m in messages if m.get("role") != "system"]
        pairs = []
        for i in range(len(non_system) - 1):
            if non_system[i].get("role") == "user" and non_system[i+1].get("role") == "assistant":
                q = non_system[i].get("content", "")[:50]
                a = non_system[i+1].get("content", "")[:50]
                if q.strip() or a.strip():
                    pairs.append(f"Q: {q}... → A: {a}...")
        recent = pairs[-rounds:] if len(pairs) >= rounds else pairs
        if not recent:
            return ""
        summary = " | ".join(recent)
        return summary[:120]  # 限制总长度

    @classmethod
    def _truncate_history(
        cls,
        messages: list[dict],
        max_rounds: int = MAX_HISTORY_ROUNDS,
        max_tokens: int = MAX_CONTEXT_TOKENS,
    ) -> list[dict]:
        """构造 LLM messages 前执行：滑动窗口截断

        Phase 8 优化:
        1. 保留最近 max_rounds 轮（2*max_rounds 条 user/assistant 消息对）
        2. 如果总 token > max_tokens，从最早的消息对开始丢弃
        3. 始终保留 system prompt 和最后一条 user question
        4. 检测指代词 → 注入前一轮上下文摘要
        """
        if not messages:
            return []

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        # Phase 8: 找到最后一条 user 消息
        last_user_idx = -1
        last_user_content = ""
        for i in range(len(other_msgs) - 1, -1, -1):
            if other_msgs[i].get("role") == "user":
                last_user_idx = i
                last_user_content = other_msgs[i].get("content", "")
                break

        # Phase 8: 检测指代词 — 若用户问题包含指代，保留更多上下文
        effective_rounds = max_rounds
        if cls._has_reference_words(last_user_content):
            effective_rounds = min(max_rounds + 5, 30)  # 额外保留 5 轮
            logger.debug("Reference words detected in question, keeping %d rounds", effective_rounds)

        if len(other_msgs) > effective_rounds * 2:
            if last_user_idx >= 0 and last_user_idx < len(other_msgs) - effective_rounds * 2:
                start = max(0, len(other_msgs) - effective_rounds * 2)
                other_msgs = other_msgs[start:]
            else:
                other_msgs = other_msgs[-(effective_rounds * 2):]

        result = system_msgs + other_msgs

        # Phase 8: token 超限时，优先保留最近的消息对 + 注入摘要
        if max_tokens > 0:
            total_chars = sum(len(m.get("content", "")) for m in result)
            estimated_tokens = total_chars // 2
            if estimated_tokens > max_tokens:
                non_system_start = len(system_msgs)
                dropped_pairs: list[dict] = []
                while estimated_tokens > max_tokens and len(result) > non_system_start + 2:
                    if non_system_start < len(result) - 2:
                        removed_q = result.pop(non_system_start)
                        estimated_tokens -= len(removed_q.get("content", "")) // 2
                        if non_system_start < len(result) - 1:
                            removed_a = result.pop(non_system_start)
                            estimated_tokens -= len(removed_a.get("content", "")) // 2
                            dropped_pairs.extend([removed_q, removed_a])
                    else:
                        break
                # Phase 8: 若丢弃了消息对，注入简短摘要到 system 之后
                if dropped_pairs and len(system_msgs) > 0:
                    summary = cls._summarize_last_rounds(dropped_pairs + (
                        other_msgs[:4] if len(other_msgs) > 4 else other_msgs
                    ), rounds=2)
                    if summary:
                        context_injection = {
                            "role": "system",
                            "content": f"[上文摘要] {summary}",
                        }
                        result.insert(len(system_msgs), context_injection)

        return result

    # ── 对话上下文装载 ──

    @staticmethod
    def _orm_msg_to_dict(msg) -> dict:
        """将 ORM Message 对象或已转换的 dict 统一转为 dict

        SQLAlchemy ORM 对象没有 model_dump()，需手动提取字段。
        兼容已有 dict 格式（如直接传入的 dict）。
        """
        if isinstance(msg, dict):
            return msg
        return {
            "role": getattr(msg, "role", ""),
            "content": getattr(msg, "content", ""),
            "metadata_json": getattr(msg, "metadata_json", None),
            "tool_call_id": getattr(msg, "tool_call_id", None),
            "token_count": getattr(msg, "token_count", 0),
        }

    @staticmethod
    def _conv_messages_to_llm_messages(messages: list) -> list[dict]:
        """将 DB 中存储的消息转换为 LLM 格式

        Phase 4: 不向 LLM 传递 tool_calls（仅用于 UI 展示），
        避免将自定义格式传递给 OpenAI API。
        """
        llm_msgs = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                llm_msgs.append({"role": "user", "content": content})
            elif role == "assistant":
                # 仅传递 content，tool_calls 元数据仅用于 UI 展示
                llm_msgs.append({"role": "assistant", "content": content})
            elif role == "tool":
                llm_msgs.append({
                    "role": "tool",
                    "content": content,
                    "tool_call_id": msg.get("tool_call_id", ""),
                })
            elif role == "tool_call":
                llm_msgs.append({
                    "role": "assistant",
                    "content": content or None,
                })
            elif role == "system":
                llm_msgs.append({"role": "system", "content": content})
        return llm_msgs

    # ── 核心方法 ──

    async def _get_kb_system_prompt(self, kb_id: int) -> str:
        """Phase 9: 获取知识库自定义 system_prompt，若未设置则返回默认。"""
        try:
            kb_repo = KBService(self.db)
            kb = await kb_repo.get_accessible(kb_id, self.user_id or 0)
            if kb and kb.system_prompt and kb.system_prompt.strip():
                return kb.system_prompt.strip()
        except Exception:
            pass
        return SYSTEM_PROMPT

    # ── Phase P0: 流式公共框架 ──

    async def _prepare_stream_context(
        self,
        kb_id: int,
        question: str,
        user_id: int,
        conv_id: int | None,
    ) -> _StreamContext:
        """构造流式对话所需的共享上下文。"""
        self.kb_id = kb_id
        self.user_id = user_id

        kb_service = KBService(self.db)
        await kb_service.get_accessible(kb_id, user_id)

        system_prompt = await self._get_kb_system_prompt(kb_id)

        conv_service = ConversationService(self.db)
        is_new_conversation = conv_id is None
        if conv_id is None:
            title = ConversationService.generate_title(question)
            conv = await conv_service.create(kb_id, user_id, title)
            conv_id = conv.id
        else:
            _ = await conv_service.get(conv_id, user_id)

        msg_repo = MessageRepository(self.db)
        history_msgs, _ = await msg_repo.list_by_conversation(conv_id, None, 1000)
        history_llm = self._conv_messages_to_llm_messages([
            self._orm_msg_to_dict(h) for h in history_msgs
        ])
        all_messages = self._truncate_history(
            [{"role": "system", "content": system_prompt}] + history_llm +
            [{"role": "user", "content": question}]
        )

        initial_state: AgentState = {
            "messages": all_messages,
            "kb_id": kb_id,
            "user_id": user_id,
            "sources": [],
            "tool_calls_log": [],
        }

        from app.agent.checkpointer import MySQLCheckpointSaver
        from app.core.database import async_session_factory
        checkpointer = (
            MySQLCheckpointSaver(async_session_factory)
            if settings.CHECKPOINT_ENABLED
            else None
        )
        config = {"configurable": {"thread_id": f"conv:{conv_id}"}}
        tools = self._build_tools()

        return _StreamContext(
            conv_id=conv_id,
            is_new_conversation=is_new_conversation,
            question=question,
            all_messages=all_messages,
            initial_state=initial_state,
            config=config,
            checkpointer=checkpointer,
            msg_repo=msg_repo,
            conv_service=conv_service,
            tools=tools,
        )

    def _build_graph_for_stream(
        self,
        stream_client,
        stream_model,
        checkpointer,
        react_mode: bool,
    ):
        """为指定流式 runner 构建 graph。

        请求级隔离：不修改 self.llm_client / self.llm_model。
        """
        if react_mode:
            from app.agent.graph_react import create_react_graph
            graph = create_react_graph(
                llm_client=stream_client,
                tools=self._build_tools(),
                model_name=stream_model,
                max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
            )
        else:
            graph = create_agent_graph(
                llm_client=stream_client,
                tools=self._build_tools(),
                model_name=stream_model,
                max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
            )
        return graph.compile(checkpointer=checkpointer)

    async def _emit_tool_frames(
        self,
        question: str,
        sources: list[dict],
    ) -> AsyncGenerator[str, None]:
        """统一发送 tool_call / tool_result / sources 事件。"""
        yield (
            f"event: tool_call\n"
            f"data: {json.dumps({'tool': 'retrieve_knowledge', 'input': {'question': question[:100]}}, ensure_ascii=False)}\n\n"
        )
        chunk_count = len(sources)
        yield (
            f"event: tool_result\n"
            f"data: {json.dumps({'tool': 'retrieve_knowledge', 'output': f'检索到 {chunk_count} 条结果', 'chunk_count': chunk_count}, ensure_ascii=False)}\n\n"
        )
        if sources:
            yield f"event: sources\ndata: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"

    def _collect_model_answer(
        self,
        ctx: _StreamContext,
        messages: list,
    ) -> str | None:
        """从 call_model 节点输出中提取增量回答，返回 delta（无增量返回 None）。"""
        prev_len = len(ctx.collected_answer)
        for m in messages:
            content = ""
            if isinstance(m, dict):
                content = m.get("content", "")
            elif hasattr(m, "content"):
                content = m.content or ""
            if content:
                ctx.collected_answer += content
        if len(ctx.collected_answer) > prev_len:
            return ctx.collected_answer[prev_len:]
        return None

    async def _run_graph_stream(
        self,
        ctx: _StreamContext,
        stream_client,
        stream_model,
        *,
        react_mode: bool,
    ) -> AsyncGenerator[str, None]:
        """节点级图流式 runner。

        react_mode=True 时允许多轮 tool_call；react_mode=False 时只发送一次 tool 事件。
        """
        graph = self._build_graph_for_stream(
            stream_client, stream_model, ctx.checkpointer, react_mode=react_mode
        )

        call_tool_done = False  # 仅非 ReAct 模式需要限制一次
        async for chunk in graph.astream(ctx.initial_state, ctx.config, stream_mode="updates"):
            node_name = list(chunk.keys())[0] if chunk else ""
            node_output = chunk.get(node_name, {}) if chunk else {}

            if node_name == "call_tool":
                log = node_output.get("tool_calls_log", [])
                sources = node_output.get("sources", [])
                ctx.all_tool_calls = log
                ctx.all_sources = sources

                # ReAct 模式：每次 call_tool 都发送工具事件；
                # 非 ReAct 模式：只发送第一次，避免重复。
                if react_mode or not call_tool_done:
                    if not react_mode:
                        call_tool_done = True
                    async for frame in self._emit_tool_frames(ctx.question, sources):
                        yield frame

            elif node_name == "call_model":
                usage = node_output.get("llm_usage")
                if usage and usage.get("prompt_tokens"):
                    ctx.llm_usage = usage
                delta = self._collect_model_answer(ctx, node_output.get("messages", []))
                if delta:
                    yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"

    async def _run_token_stream(
        self,
        ctx: _StreamContext,
        stream_client,
        stream_model,
    ) -> AsyncGenerator[str, None]:
        """Token 级流式 runner（STREAMING_TOKEN_LEVEL）。"""
        from app.agent.graph import _lc_message_to_dict

        graph = create_agent_graph(
            llm_client=stream_client,
            tools=ctx.tools,
            model_name=stream_model,
        )
        compiled = graph.compile(
            checkpointer=ctx.checkpointer,
            interrupt_after=["call_tool"],
        )

        tool_state = await compiled.ainvoke(ctx.initial_state, ctx.config)
        ctx.all_tool_calls = tool_state.get("tool_calls_log", [])
        ctx.all_sources = tool_state.get("sources", [])

        async for frame in self._emit_tool_frames(ctx.question, ctx.all_sources):
            yield frame

        # 提取当前问题（兼容 dict 与 LangChain HumanMessage）
        current_question = ""
        for m in reversed(tool_state.get("messages", [])):
            if isinstance(m, dict) and m.get("role") == "user":
                current_question = m.get("content", "")
                break
            if type(m).__name__ == "HumanMessage":
                current_question = getattr(m, "content", "")
                break

        context_parts = []
        for idx, src in enumerate(ctx.all_sources, start=1):
            content = src.get("content", "") if isinstance(src, dict) else getattr(src, "content", "")
            doc_id = src.get("document_id", "") if isinstance(src, dict) else getattr(src, "document_id", "")
            title = f" (文档:{doc_id})" if doc_id else ""
            context_parts.append(f"[来源 {idx}]{title}\n{content.strip()}")
        context = "\n\n---\n\n".join(context_parts)

        rag_prompt = f"""参考资料：
{context}

用户问题：{current_question}

请用中文回答。如果参考资料不足以回答问题，请明确说明。
重要：回答时使用 [source:N] 格式标注引用来源（N 为来源编号）。"""

        messages_for_llm: list = [
            {
                "role": "system",
                "content": (
                    "你是一个智能知识库助手。请根据参考资料回答用户问题。"
                    "用中文回答。如果参考资料不足以回答问题，请明确说明。"
                    "回答时引用来源编号。"
                ),
            },
            {"role": "user", "content": rag_prompt},
        ]
        api_messages = [_lc_message_to_dict(m) for m in messages_for_llm]

        stream = await stream_client.chat.completions.create(
            model=stream_model,
            messages=api_messages,
            temperature=0.3,
            max_tokens=2048,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if hasattr(chunk, 'usage') and chunk.usage:
                ctx.llm_usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                ctx.collected_answer += delta.content
                yield f"data: {json.dumps(delta.content, ensure_ascii=False)}\n\n"

        await compiled.aupdate_state(
            ctx.config,
            {
                "messages": [{"role": "assistant", "content": ctx.collected_answer}],
                "sources": ctx.all_sources,
                "tool_calls_log": ctx.all_tool_calls,
            },
        )

    async def _with_cloud_fallback(
        self,
        ctx: _StreamContext,
        runner,
    ) -> AsyncGenerator[str, None]:
        """包装流式 runner，云端异常时自动 fallback 到本地 Ollama。"""
        try:
            async for frame in runner(ctx, self.llm_client, self.llm_model):
                yield frame
        except _CLOUD_FALLBACK_EXCEPTIONS as cloud_err:
            logger.warning(
                "Cloud LLM streaming failed conv=%d provider=%s error=%s, falling back",
                ctx.conv_id, settings.LLM_PROVIDER, type(cloud_err).__name__,
            )
            fb_client, fb_model, is_fb = await self._try_cloud_fallback()
            if not is_fb:
                raise cloud_err
            await self._cleanup_orphan_checkpoint(ctx.conv_id)
            ctx.reset_for_fallback()
            async for frame in runner(ctx, fb_client, fb_model):
                yield frame

    async def _finalize_stream(
        self,
        ctx: _StreamContext,
        background_tasks,
    ) -> AsyncGenerator[str, None]:
        """流式结束后的统一收尾：计费、持久化、done 事件、后台标题。"""
        try:
            if ctx.llm_usage and ctx.llm_usage.get("prompt_tokens"):
                input_tokens = ctx.llm_usage["prompt_tokens"]
                output_tokens = ctx.llm_usage.get("completion_tokens", 0) or len(ctx.collected_answer) // 2
            else:
                input_tokens = sum(len(msg.get("content", "")) for msg in ctx.all_messages) // 2
                output_tokens = len(ctx.collected_answer) // 2
            token_count = output_tokens
            await self._record_cost(input_tokens, output_tokens)

            await self._persist_messages(
                ctx.msg_repo, ctx.conv_service, ctx.conv_id,
                ctx.question, ctx.collected_answer,
                ctx.all_tool_calls, ctx.all_sources, token_count,
            )

            citations = build_citation_info(parse_citations(ctx.collected_answer), ctx.all_sources)
            follow_ups = await self._generate_follow_up_questions(ctx.question, ctx.collected_answer)
            done_payload = json.dumps({
                "conversation_id": ctx.conv_id,
                "total_tokens": token_count,
                "tool_calls_count": len(ctx.all_tool_calls),
                "fallback": self._fallback_triggered,
                "citations": citations,
                "follow_up_questions": follow_ups,
            }, ensure_ascii=False)
            yield (
                f"event: done\n"
                f"data: {done_payload}\n\n"
            )

            if ctx.is_new_conversation and background_tasks:
                background_tasks.add_task(
                    self._update_title_async,
                    ctx.conv_id, self.user_id, ctx.question, ctx.collected_answer,
                )
        except Exception as e:
            logger.exception("Agent stream failed")
            yield f"event: error\ndata: {json.dumps({'code': 'AGENT_ERROR', 'message': str(e)}, ensure_ascii=False)}\n\n"
            try:
                token_count = len(ctx.collected_answer) // 2
                await self._persist_messages(
                    ctx.msg_repo, ctx.conv_service, ctx.conv_id,
                    ctx.question, ctx.collected_answer or f"抱歉，处理出错: {str(e)}",
                    ctx.all_tool_calls, ctx.all_sources, token_count,
                )
            except Exception as e2:
                logger.error("持久化失败 conv=%d: %s", ctx.conv_id, e2)
                await self._cleanup_orphan_checkpoint(ctx.conv_id)

    async def chat(
        self,
        kb_id: int,
        question: str,
        user_id: int,
        conv_id: int | None = None,
    ) -> AgentChatResponse:
        """Agent 非流式对话（Phase 4: 集成 Checkpointer + 语义标题）"""
        self.kb_id = kb_id
        self.user_id = user_id

        kb_service = KBService(self.db)
        await kb_service.get_accessible(kb_id, user_id)

        # Phase 9: 使用 KB 自定义 system_prompt（若配置）
        system_prompt = await self._get_kb_system_prompt(kb_id)

        conv_service = ConversationService(self.db)
        is_new_conversation = conv_id is None
        if conv_id is None:
            title = ConversationService.generate_title(question)
            conv = await conv_service.create(kb_id, user_id, title)
            conv_id = conv.id
        else:
            _ = await conv_service.get(conv_id, user_id)

        msg_repo = MessageRepository(self.db)
        history_msgs, _ = await msg_repo.list_by_conversation(conv_id, None, 1000)

        history_llm = self._conv_messages_to_llm_messages([
            self._orm_msg_to_dict(h) for h in history_msgs
        ])
        all_messages = self._truncate_history(
            [{"role": "system", "content": system_prompt}] + history_llm +
            [{"role": "user", "content": question}]
        )

        initial_state: AgentState = {
            "messages": all_messages,
            "kb_id": kb_id,
            "user_id": user_id,
            "sources": [],
            "tool_calls_log": [],
        }

        from app.agent.checkpointer import MySQLCheckpointSaver
        from app.core.database import async_session_factory
        checkpointer = (
            MySQLCheckpointSaver(async_session_factory)
            if settings.CHECKPOINT_ENABLED
            else None
        )
        graph = self._get_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"conv:{conv_id}"}}

        answer = ""
        sources: list[dict] = []
        tool_calls_log: list[dict] = []
        token_count = 0

        # Phase 6: 成本上限检查（云端 LLM 调用前）
        await self._check_cost_limits()

        async def _execute_with_fallback():
            """执行 graph.ainvoke，云端异常时自动 fallback 重试。"""
            try:
                return await graph.ainvoke(initial_state, config)
            except _CLOUD_FALLBACK_EXCEPTIONS as cloud_err:
                logger.warning(
                    "Cloud LLM failed conv=%d provider=%s error=%s, attempting fallback",
                    conv_id, settings.LLM_PROVIDER, type(cloud_err).__name__,
                )
                fb_client, fb_model, is_fb = await self._try_cloud_fallback()
                if not is_fb:
                    raise cloud_err
                # 清理失败执行留下的 orphan checkpoint（含格式不兼容的 pending_writes）
                await self._cleanup_orphan_checkpoint(conv_id)
                # 用 fallback 客户端重建 graph（不持久化到 self，请求级别隔离）
                orig_client, orig_model = self.llm_client, self.llm_model
                try:
                    self.llm_client, self.llm_model = fb_client, fb_model
                    fb_graph = self._get_graph(checkpointer=checkpointer)
                    return await fb_graph.ainvoke(initial_state, config)
                finally:
                    self.llm_client, self.llm_model = orig_client, orig_model

        try:
            final_state = await _execute_with_fallback()

            result_msgs = final_state.get("messages", [])
            for m in reversed(result_msgs):
                if isinstance(m, dict):
                    if m.get("role") == "assistant" and m.get("content"):
                        answer = m["content"]
                        break
                elif hasattr(m, "content") and hasattr(m, "type"):
                    # LangChain AIMessage 对象 (isinstance 更稳健, 兼容 type 值异常)
                    from langchain_core.messages import AIMessage
                    if isinstance(m, AIMessage):
                        if m.content:
                            answer = m.content
                            break
                    elif str(m.type).strip() == "ai" and m.content:
                        answer = m.content
                        break
                elif hasattr(m, "content"):
                    # 其他有 content 属性的对象
                    content = m.content
                    if content:
                        answer = str(content)
                        break

            sources = final_state.get("sources", [])
            tool_calls_log = final_state.get("tool_calls_log", [])

            # 若检索结果为空且 answer 为空，返回友好提示
            if not answer or not answer.strip():
                if not sources:
                    answer = "抱歉，我在当前知识库中没有找到相关信息。请尝试：\n"
                    answer += "1. 换一种方式描述您的问题\n"
                    answer += "2. 确认知识库中已上传相关文档\n"
                    answer += "3. 使用更具体的关键词重新提问"
                else:
                    answer = "已检索到相关文档内容，但未能生成有效回答。请尝试重新提问或调整问题表述。"
            # Phase 7: 优先使用 LLM 返回的真实 usage，无 usage 时回退估算
            llm_usage = final_state.get("llm_usage")
            if llm_usage and llm_usage.get("prompt_tokens"):
                input_tokens = llm_usage["prompt_tokens"]
                output_tokens = llm_usage.get("completion_tokens", 0) or len(answer) // 2
            else:
                input_tokens = sum(len(m.get("content", "")) for m in all_messages) // 2
                output_tokens = len(answer) // 2
            token_count = output_tokens
            await self._record_cost(input_tokens, output_tokens)

            await self._persist_messages(
                msg_repo, conv_service, conv_id, question, answer,
                tool_calls_log, sources, token_count,
            )
        except Exception:
            # 持久化失败 → 清理当前 thread 的 orphan checkpoint
            logger.exception("Agent chat failed conv=%d", conv_id)
            await self._cleanup_orphan_checkpoint(conv_id)
            raise

        if is_new_conversation:
            try:
                title = await asyncio.wait_for(
                    ConversationService.generate_semantic_title(
                        question, answer, self.llm_client,
                    ),
                    timeout=5.0,
                )
                await conv_service.update_title(conv_id, user_id, title)
            except (asyncio.TimeoutError, Exception):
                pass

        # Phase 8: 解析答案中的 [source:N] 引用标记
        citation_indices = parse_citations(answer)
        citation_info = build_citation_info(citation_indices, sources)

        # Phase 8 P1.3: 生成推荐问题
        follow_ups = await self._generate_follow_up_questions(question, answer)

        # Phase 10: Agent chat 审计日志
        from app.services.audit_service import log_event, AuditAction
        await log_event(self.db, user_id, AuditAction.AGENT_CHAT, "conversation", conv_id,
                        details={"kb_id": kb_id, "token_count": token_count,
                                  "provider": settings.LLM_PROVIDER, "fallback": self._fallback_triggered})

        return AgentChatResponse(
            conversation_id=conv_id,
            answer=answer,
            sources=[SearchResult(**s) for s in sources],
            tool_calls=[
                ToolCallInfo(tool=t["tool"], input=t["input"], output=t["output"])
                for t in tool_calls_log
            ],
            token_count=token_count,
            fallback=self._fallback_triggered,
            citations=[CitationInfo(**c) for c in citation_info],
            follow_up_questions=follow_ups,
        )

    async def chat_stream(
        self,
        kb_id: int,
        question: str,
        user_id: int,
        conv_id: int | None = None,
        background_tasks=None,
    ):
        """Agent 流式对话（Phase P0：三种路径共享公共框架）。

        - REACT_ENABLED=true → graph_react 节点级输出（STREAMING_TOKEN_LEVEL 被忽略）
        - STREAMING_TOKEN_LEVEL=true → 方案 A interrupt_after 逐 token SSE
        - 否则 → Phase 4 节点级输出（降级）
        """
        ctx = await self._prepare_stream_context(kb_id, question, user_id, conv_id)
        await self._check_cost_limits()

        yield f"event: thought\ndata: {json.dumps({'content': '正在检索相关知识...'}, ensure_ascii=False)}\n\n"

        if settings.REACT_ENABLED:
            runner = lambda c, client, model: self._run_graph_stream(c, client, model, react_mode=True)
        elif settings.STREAMING_TOKEN_LEVEL:
            runner = self._run_token_stream
        else:
            runner = lambda c, client, model: self._run_graph_stream(c, client, model, react_mode=False)

        async for frame in self._with_cloud_fallback(ctx, runner):
            yield frame

        async for frame in self._finalize_stream(ctx, background_tasks):
            yield frame

    async def _generate_follow_up_questions(
        self, question: str, answer: str,
    ) -> list[str]:
        """Phase 8: 基于当前问答生成 3 个推荐后续问题。

        使用低温度以避免重复/无关推荐。
        失败时返回空列表（不影响主流程）。
        """
        if not answer or len(answer) < 20:
            return []
        try:
            prompt = FOLLOW_UP_PROMPT.format(question=question[:300], answer=answer[:800])
            response = await self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=150,
            )
            text = response.choices[0].message.content or ""
            lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
            # 过滤超长行和明显不是问题的行
            questions = [
                l for l in lines
                if len(l) <= 60 and ("?" in l or "？" in l or "什么" in l or "如何" in l or "怎么" in l or "哪些" in l or "哪个" in l or len(l) > 8)
            ]
            return questions[:3]
        except Exception as e:
            logger.debug("Follow-up question generation failed: %s", e)
            return []

    async def _cleanup_orphan_checkpoint(self, conv_id: int) -> None:
        """清理 orphan checkpoint 数据，避免残留数据污染后续对话恢复。

        当 Agent 对话持久化失败（非流式 ainvoke 异常或流式 persist 失败），
        LangGraph checkpointer 可能已写入 checkpoint_writes/pending_writes，
        这些数据无法通过正常对话路径消费，形成孤儿记录。
        """
        try:
            from app.agent.checkpointer import MySQLCheckpointSaver
            from app.core.database import async_session_factory
            from sqlalchemy import delete
            from app.models.checkpoint import AgentCheckpoint as CK

            async with async_session_factory() as db:
                result = await db.execute(
                    delete(CK).where(
                        CK.thread_id == f"conv:{conv_id}"
                    )
                )
                await db.commit()
                deleted = result.rowcount
                if deleted:
                    logger.info(
                        "Cleaned %d orphan checkpoints for conv=%d", deleted, conv_id
                    )
        except Exception:
            logger.exception(
                "Failed to clean orphan checkpoints for conv=%d", conv_id
            )

    async def _update_title_async(self, conv_id: int, user_id: int,
                                   question: str, answer: str):
        """后台异步更新标题（使用独立 AsyncSession，不持有 request-scoped 会话）"""
        from app.core.database import async_session_factory
        from app.services.conversation_service import ConversationService

        async with async_session_factory() as db:
            conv_service = ConversationService(db)
            try:
                title = await ConversationService.generate_semantic_title(
                    question, answer, self.llm_client,
                )
                await conv_service.update_title(conv_id, user_id, title)
                logger.info("语义标题生成成功 conv=%d title=%s", conv_id, title)
            except Exception as e:
                logger.warning("语义标题生成失败 conv=%d: %s", conv_id, e)

    async def _persist_messages(
        self, msg_repo, conv_service, conv_id, question, answer,
        tool_calls_log, sources, token_count,
        follow_up_questions: list[str] | None = None,
    ):
        """持久化对话消息

        Phase 4: tool_calls_log 存储在 metadata_json.tool_calls_log 字段
        （非 tool_calls），避免与 OpenAI 标准格式混淆。
        Phase 8: follow_up_questions 存入 metadata 供前端回显。
        """
        try:
            await msg_repo.create({
                "conversation_id": conv_id,
                "role": "user",
                "content": question,
                "token_count": len(question) // 2,
            })
            await conv_service.conv_repo.increment_message_count(conv_id)

            metadata = {
                "tool_calls_log": [
                    {
                        "tool": t["tool"] if isinstance(t, dict) else t.tool,
                        "input": t["input"] if isinstance(t, dict) else t.input,
                        "output": t["output"] if isinstance(t, dict) else t.output,
                    }
                    for t in tool_calls_log
                ],
                "sources": sources,
                "follow_up_questions": follow_up_questions or [],
            }
            await msg_repo.create({
                "conversation_id": conv_id,
                "role": "assistant",
                "content": answer,
                "token_count": token_count,
                "metadata_json": json.dumps(metadata, ensure_ascii=False, default=str),
            })
            await conv_service.conv_repo.increment_message_count(conv_id)

        except Exception as e:
            logger.error("持久化 Agent 对话消息失败: %s", str(e))
