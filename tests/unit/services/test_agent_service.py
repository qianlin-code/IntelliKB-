"""
Unit tests for app.services.agent_service

目标：覆盖 chat_stream 三条路径的公共框架与行为等价性。
使用 unittest.mock 隔离 DB、LLM、LangGraph。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from openai import AsyncOpenAI

from app.services.agent_service import AgentService, _StreamContext


@pytest.fixture
def service():
    """返回已 mock 掉 __init__ 的 AgentService 实例。"""
    with patch.object(AgentService, "__init__", lambda self, db: None):
        svc = AgentService(None)
        svc.db = None
        svc.llm_client = MagicMock()
        svc.llm_model = "test-model"
        svc.kb_id = None
        svc.user_id = None
        svc._fallback_triggered = False
        yield svc


@pytest.fixture
def base_ctx():
    """最小可用的 _StreamContext。"""
    return _StreamContext(
        conv_id=42,
        is_new_conversation=True,
        question="测试问题",
        all_messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "测试问题"}],
        initial_state={"messages": [], "kb_id": 1, "user_id": 1, "sources": [], "tool_calls_log": []},
        config={"configurable": {"thread_id": "conv:42"}},
        checkpointer=None,
        msg_repo=MagicMock(),
        conv_service=MagicMock(),
        tools=[],
    )


class TestStreamContext:
    """_StreamContext 数据对象"""

    def test_reset_for_fallback(self, base_ctx):
        base_ctx.collected_answer = "已有回答"
        base_ctx.all_sources = [{"chunk_id": 1}]
        base_ctx.all_tool_calls = [{"tool": "retrieve"}]
        base_ctx.llm_usage = {"prompt_tokens": 10}

        base_ctx.reset_for_fallback()

        assert base_ctx.collected_answer == ""
        assert base_ctx.all_sources == []
        assert base_ctx.all_tool_calls == []
        assert base_ctx.llm_usage is None


class TestEmitToolFrames:
    """_emit_tool_frames 统一工具事件"""

    @pytest.mark.asyncio
    async def test_emits_tool_call_result_sources(self, service):
        sources = [{"chunk_id": 1, "document_id": 10, "content": "abc"}]
        frames = []
        async for frame in service._emit_tool_frames("long question here", sources):
            frames.append(frame)

        assert len(frames) == 3
        assert "event: tool_call" in frames[0]
        assert "retrieve_knowledge" in frames[0]
        assert "long question" in frames[0]
        assert "event: tool_result" in frames[1]
        assert "1 条结果" in frames[1]
        assert "event: sources" in frames[2]
        assert json.loads(frames[2].split("data: ", 1)[1]) == {"sources": sources}

    @pytest.mark.asyncio
    async def test_no_sources_event_when_empty(self, service):
        frames = []
        async for frame in service._emit_tool_frames("q", []):
            frames.append(frame)
        assert len(frames) == 2
        assert all("event: sources" not in f for f in frames)


class TestCollectModelAnswer:
    """_collect_model_answer 增量收集"""

    def test_collects_dict_and_lc_messages(self, service, base_ctx):
        delta = service._collect_model_answer(base_ctx, [
            {"role": "assistant", "content": "你好"},
            MagicMock(content="，世界"),
        ])
        assert delta == "你好，世界"
        assert base_ctx.collected_answer == "你好，世界"

    def test_returns_none_when_no_new_content(self, service, base_ctx):
        base_ctx.collected_answer = "已有"
        delta = service._collect_model_answer(base_ctx, [{"role": "assistant", "content": ""}])
        assert delta is None


class TestRunGraphStream:
    """_run_graph_stream 节点级流式"""

    @pytest.mark.asyncio
    async def test_react_mode_emits_multiple_tool_frames(self, service, base_ctx):
        """react_mode=True 时，每个 call_tool 都发送工具事件。"""
        graph = MagicMock()
        graph.astream = MagicMock(return_value=async_iter([
            {"call_tool": {"tool_calls_log": [{"tool": "t1"}], "sources": [{"chunk_id": 1}]}},
            {"call_tool": {"tool_calls_log": [{"tool": "t2"}], "sources": [{"chunk_id": 2}]}},
            {"call_model": {"messages": [{"role": "assistant", "content": "答"}], "llm_usage": {"prompt_tokens": 5, "completion_tokens": 1}}},
        ]))

        with patch.object(service, "_build_graph_for_stream", return_value=graph):
            frames = [f async for f in service._run_graph_stream(base_ctx, MagicMock(), "m", react_mode=True)]

        events = [extract_event(f) for f in frames]
        assert events.count("tool_call") == 2
        assert events.count("tool_result") == 2
        assert events.count("sources") == 2
        assert events.count("") == 1  # data-only token
        assert base_ctx.llm_usage == {"prompt_tokens": 5, "completion_tokens": 1}
        assert base_ctx.collected_answer == "答"

    @pytest.mark.asyncio
    async def test_non_react_mode_emits_single_tool_frame(self, service, base_ctx):
        """react_mode=False 时，只发送第一次 call_tool 的工具事件。"""
        graph = MagicMock()
        graph.astream = MagicMock(return_value=async_iter([
            {"call_tool": {"tool_calls_log": [{"tool": "t1"}], "sources": [{"chunk_id": 1}]}},
            {"call_tool": {"tool_calls_log": [{"tool": "t2"}], "sources": [{"chunk_id": 2}]}},
            {"call_model": {"messages": [{"role": "assistant", "content": "答"}]}},
        ]))

        with patch.object(service, "_build_graph_for_stream", return_value=graph):
            frames = [f async for f in service._run_graph_stream(base_ctx, MagicMock(), "m", react_mode=False)]

        events = [extract_event(f) for f in frames]
        assert events.count("tool_call") == 1
        assert events.count("tool_result") == 1
        assert events.count("sources") == 1
        assert base_ctx.collected_answer == "答"


class TestRunTokenStream:
    """_run_token_stream 逐 token 流式"""

    @pytest.mark.asyncio
    async def test_token_stream_collects_usage(self, service, base_ctx):
        compiled = MagicMock()
        compiled.ainvoke = AsyncMock(return_value={
            "tool_calls_log": [{"tool": "retrieve"}],
            "sources": [{"chunk_id": 1, "content": "c1", "document_id": 10}],
            "messages": [{"role": "user", "content": "测试问题"}],
        })
        compiled.aupdate_state = AsyncMock()

        graph = MagicMock()
        graph.compile = MagicMock(return_value=compiled)

        usage_mock = MagicMock(prompt_tokens=3, completion_tokens=1)
        chunk1 = MagicMock(usage=None, choices=[MagicMock(delta=MagicMock(content="回"))])
        chunk2 = MagicMock(usage=usage_mock, choices=[])
        llm_stream = async_iter([chunk1, chunk2])

        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=llm_stream)

        with patch("app.services.agent_service.create_agent_graph", return_value=graph):
            frames = [f async for f in service._run_token_stream(base_ctx, client, "m")]

        events = [extract_event(f) for f in frames]
        assert "tool_call" in events
        assert "sources" in events
        assert base_ctx.collected_answer == "回"
        assert base_ctx.llm_usage == {"prompt_tokens": 3, "completion_tokens": 1}
        compiled.aupdate_state.assert_awaited_once()


class TestWithCloudFallback:
    """_with_cloud_fallback 云端异常 fallback"""

    @pytest.mark.asyncio
    async def test_fallback_resets_context_and_retries(self, service, base_ctx):
        """云端失败后切换 fallback 客户端并重置 ctx。"""
        service.llm_client = MagicMock()
        service.llm_model = "cloud-model"
        service._fallback_triggered = False

        async def runner(ctx, client, model):
            if client is not fb_client:
                raise TimeoutError("cloud down")
            ctx.collected_answer = "fallback answer"
            yield "data: fallback\n\n"

        fb_client = MagicMock()

        async def mock_try_fallback():
            service._fallback_triggered = True
            return fb_client, "fb-model", True

        with patch.object(service, "_try_cloud_fallback", new=mock_try_fallback):
            with patch.object(service, "_cleanup_orphan_checkpoint", new=AsyncMock()):
                frames = [f async for f in service._with_cloud_fallback(base_ctx, runner)]

        assert service._fallback_triggered is True
        assert base_ctx.collected_answer == "fallback answer"
        assert frames == ["data: fallback\n\n"]

    @pytest.mark.asyncio
    async def test_no_fallback_when_not_cloud_exception(self, service, base_ctx):
        async def runner(ctx, client, model):
            raise ValueError("business error")
            yield  # unreachable, but makes it an async generator

        with patch.object(service, "_try_cloud_fallback") as mock_fb:
            with pytest.raises(ValueError, match="business error"):
                async for _ in service._with_cloud_fallback(base_ctx, runner):
                    pass
        mock_fb.assert_not_called()


class TestFinalizeStream:
    """_finalize_stream 统一收尾"""

    @pytest.mark.asyncio
    async def test_finalize_emits_done_and_persists(self, service, base_ctx):
        service._record_cost = AsyncMock()
        service._persist_messages = AsyncMock()
        service._generate_follow_up_questions = AsyncMock(return_value=["q1", "q2"])

        base_ctx.collected_answer = "答案是 [source:1]"
        base_ctx.all_sources = [{"chunk_id": 1, "document_id": 10}]
        base_ctx.llm_usage = {"prompt_tokens": 10, "completion_tokens": 2}

        frames = [f async for f in service._finalize_stream(base_ctx, None)]

        assert len(frames) == 1
        assert "event: done" in frames[0]
        data = json.loads(frames[0].split("data: ", 1)[1])
        assert data["conversation_id"] == 42
        assert data["total_tokens"] == 2
        assert data["fallback"] is False
        assert len(data["citations"]) == 1
        assert data["follow_up_questions"] == ["q1", "q2"]
        service._record_cost.assert_awaited_once_with(10, 2)
        service._persist_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_finalize_error_event_on_persist_failure(self, service, base_ctx):
        service._record_cost = AsyncMock()
        service._persist_messages = AsyncMock(side_effect=RuntimeError("db locked"))
        service._cleanup_orphan_checkpoint = AsyncMock()

        base_ctx.collected_answer = "answer"
        frames = [f async for f in service._finalize_stream(base_ctx, None)]

        assert any("event: error" in f for f in frames)
        service._cleanup_orphan_checkpoint.assert_awaited_once_with(42)


class TestChatStream:
    """chat_stream 端到端组合行为"""

    @pytest.mark.asyncio
    async def test_chat_stream_runs_graph_node_path(self, service):
        """默认路径（非 REACT、非 TOKEN）产生完整事件序列。"""
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.REACT_ENABLED = False
            mock_settings.STREAMING_TOKEN_LEVEL = False
            mock_settings.CHECKPOINT_ENABLED = False
            mock_settings.LLM_PROVIDER = "ollama"

            service._prepare_stream_context = AsyncMock(return_value=_base_ctx_fixture(service))
            service._check_cost_limits = AsyncMock()
            service._run_graph_stream = MagicMock(return_value=async_iter([
                "event: tool_call\ndata: {}\n\n",
                "data: \"回\"\n\n",
            ]))
            service._finalize_stream = MagicMock(return_value=async_iter([
                "event: done\ndata: {\"total_tokens\":1}\n\n",
            ]))

            frames = [f async for f in service.chat_stream(1, "q", 1)]

        events = [extract_event(f) for f in frames]
        assert events[0] == "thought"
        assert "tool_call" in events
        assert "" in events  # token
        assert "done" in events


class TestCostAndFallback:
    """成本检查、记录与云端 fallback"""

    @pytest.mark.asyncio
    async def test_check_cost_limits_skips_ollama(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            await service._check_cost_limits()  # should not raise

    @pytest.mark.asyncio
    async def test_check_cost_limits_raises_when_exceeded(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "deepseek"
            with patch("app.core.cost_tracker.check_limits", new=AsyncMock(return_value=(True, "月度限额已用完"))):
                with pytest.raises(Exception) as exc_info:
                    await service._check_cost_limits()
                assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_record_cost_skips_ollama(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            await service._record_cost(10, 2)

    @pytest.mark.asyncio
    async def test_record_cost_records_cloud(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "deepseek"
            with patch("app.core.cost_tracker.record_usage", new=AsyncMock()) as mock_record:
                await service._record_cost(10, 2)
                mock_record.assert_awaited_once_with(10, 2)

    @pytest.mark.asyncio
    async def test_try_cloud_fallback_returns_ollama_when_provider_is_ollama(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            client, model, is_fb = await service._try_cloud_fallback()
            assert client is service.llm_client
            assert model == service.llm_model
            assert is_fb is False

    @pytest.mark.asyncio
    async def test_try_cloud_fallback_returns_fallback_client(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "deepseek"
            mock_settings.OLLAMA_BASE_URL = "http://localhost:11434/v1"
            mock_settings.OLLAMA_API_KEY = "dummy"
            mock_settings.LLM_TIMEOUT_SECONDS = 30
            mock_settings.AGENT_MODEL = "qwen2.5:7b"
            client, model, is_fb = await service._try_cloud_fallback()
            assert isinstance(client, AsyncOpenAI)
            assert model == "qwen2.5:7b"
            assert is_fb is True
            assert service._fallback_triggered is True

    @pytest.mark.asyncio
    async def test_try_cloud_fallback_returns_original_on_exception(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "deepseek"
            mock_settings.OLLAMA_BASE_URL = None  # will raise in AsyncOpenAI init
            client, model, is_fb = await service._try_cloud_fallback()
            assert client is service.llm_client
            assert is_fb is False


class TestCleanupAndTitle:
    """orphan checkpoint 清理与标题更新"""

    @pytest.mark.asyncio
    async def test_cleanup_orphan_checkpoint_deletes_records(self, service):
        with patch("app.core.database.async_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_result = MagicMock()
            mock_result.rowcount = 3
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            await service._cleanup_orphan_checkpoint(42)

            mock_session.execute.assert_awaited_once()
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_orphan_checkpoint_logs_exception(self, service):
        with patch("app.core.database.async_session_factory") as mock_factory:
            mock_factory.side_effect = RuntimeError("db down")
            await service._cleanup_orphan_checkpoint(42)  # should not raise

    @pytest.mark.asyncio
    async def test_update_title_async_updates_title(self, service):
        with patch("app.core.database.async_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.services.conversation_service.ConversationService") as MockConv:
                mock_conv_service = MagicMock()
                mock_conv_service.update_title = AsyncMock()
                MockConv.return_value = mock_conv_service
                MockConv.generate_semantic_title = AsyncMock(return_value="新标题")

                await service._update_title_async(7, 1, "q", "a" * 30)

                mock_conv_service.update_title.assert_awaited_once_with(7, 1, "新标题")


class TestChatNonStream:
    """chat() 非流式对话"""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, service):
        with patch("app.services.agent_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock(return_value=MagicMock(system_prompt=""))
            with patch.object(service, "_get_kb_system_prompt", new=AsyncMock(return_value="sys")):
                with patch("app.services.agent_service.ConversationService") as MockConv:
                    mock_conv = MagicMock()
                    mock_conv.id = 9
                    MockConv.return_value.create = AsyncMock(return_value=mock_conv)
                    MockConv.return_value.get = AsyncMock()
                    MockConv.return_value.update_title = AsyncMock()
                    MockConv.generate_semantic_title = AsyncMock(return_value="标题")
                    with patch("app.services.agent_service.MessageRepository") as MockMsg:
                        MockMsg.return_value.list_by_conversation = AsyncMock(return_value=([], 0))
                        MockMsg.return_value.create = AsyncMock()
                        with patch("app.services.agent_service.settings") as mock_settings:
                            mock_settings.CHECKPOINT_ENABLED = False
                            mock_settings.LLM_PROVIDER = "ollama"

                            graph = MagicMock()
                            graph.ainvoke = AsyncMock(return_value={
                                "messages": [{"role": "assistant", "content": "回答 [source:1]"}],
                                "sources": [{"chunk_id": 1, "document_id": 10, "content": "c1", "score": 0.9}],
                                "tool_calls_log": [{"tool": "retrieve", "input": {}, "output": "o"}],
                            })
                            service._get_graph = MagicMock(return_value=graph)
                            service._check_cost_limits = AsyncMock()
                            service._record_cost = AsyncMock()
                            service._persist_messages = AsyncMock()
                            service._generate_follow_up_questions = AsyncMock(return_value=["q1"])

                            with patch("app.services.audit_service.log_event", new=AsyncMock()):
                                with patch("app.services.agent_service.parse_citations", return_value=[1]):
                                    with patch("app.services.agent_service.build_citation_info", return_value=[{"source_index": 1, "chunk_id": 1, "document_id": 10, "excerpt": "c1"}]):
                                        result = await service.chat(1, "问题", 1)

                            assert result.conversation_id == 9
                            assert "回答" in result.answer
                            assert len(result.sources) == 1
                            assert len(result.follow_up_questions) == 1

    @pytest.mark.asyncio
    async def test_chat_fallback_on_cloud_error(self, service):
        service._fallback_triggered = False

        async def mock_try_fallback():
            service._fallback_triggered = True
            return MagicMock(), "fb-model", True

        with patch("app.services.agent_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock(return_value=MagicMock(system_prompt=""))
            with patch.object(service, "_get_kb_system_prompt", new=AsyncMock(return_value="sys")):
                with patch("app.services.agent_service.ConversationService") as MockConv:
                    mock_conv = MagicMock()
                    mock_conv.id = 10
                    MockConv.return_value.create = AsyncMock(return_value=mock_conv)
                    MockConv.return_value.get = AsyncMock()
                    with patch("app.services.agent_service.MessageRepository") as MockMsg:
                        MockMsg.return_value.list_by_conversation = AsyncMock(return_value=([], 0))
                        MockMsg.return_value.create = AsyncMock()
                        with patch("app.services.agent_service.settings") as mock_settings:
                            mock_settings.CHECKPOINT_ENABLED = False
                            mock_settings.LLM_PROVIDER = "deepseek"

                            failing_graph = MagicMock()
                            failing_graph.ainvoke = AsyncMock(side_effect=openai.APITimeoutError("timeout"))
                            success_graph = MagicMock()
                            success_graph.ainvoke = AsyncMock(return_value={
                                "messages": [{"role": "assistant", "content": "fallback answer"}],
                                "sources": [],
                                "tool_calls_log": [],
                            })

                            def graph_side_effect(*args, **kwargs):
                                return failing_graph if service.llm_client == service._orig_client else success_graph

                            service._orig_client = service.llm_client
                            service._get_graph = MagicMock(side_effect=graph_side_effect)
                            service._check_cost_limits = AsyncMock()
                            service._record_cost = AsyncMock()
                            service._persist_messages = AsyncMock()
                            service._generate_follow_up_questions = AsyncMock(return_value=[])
                            service._cleanup_orphan_checkpoint = AsyncMock()

                            with patch.object(service, "_try_cloud_fallback", new=mock_try_fallback):
                                with patch("app.services.audit_service.log_event", new=AsyncMock()):
                                    with patch("app.services.agent_service.parse_citations", return_value=[]):
                                        with patch("app.services.agent_service.build_citation_info", return_value=[]):
                                            result = await service.chat(1, "问题", 1)

                            assert "fallback answer" in result.answer
                            assert service._fallback_triggered is True

    @pytest.mark.asyncio
    async def test_chat_handles_empty_answer_without_sources(self, service):
        with patch("app.services.agent_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock(return_value=MagicMock(system_prompt=""))
            with patch.object(service, "_get_kb_system_prompt", new=AsyncMock(return_value="sys")):
                with patch("app.services.agent_service.ConversationService") as MockConv:
                    mock_conv = MagicMock()
                    mock_conv.id = 11
                    MockConv.return_value.create = AsyncMock(return_value=mock_conv)
                    MockConv.return_value.get = AsyncMock()
                    with patch("app.services.agent_service.MessageRepository") as MockMsg:
                        MockMsg.return_value.list_by_conversation = AsyncMock(return_value=([], 0))
                        MockMsg.return_value.create = AsyncMock()
                        with patch("app.services.agent_service.settings") as mock_settings:
                            mock_settings.CHECKPOINT_ENABLED = False
                            mock_settings.LLM_PROVIDER = "ollama"

                            graph = MagicMock()
                            graph.ainvoke = AsyncMock(return_value={
                                "messages": [{"role": "assistant", "content": ""}],
                                "sources": [],
                                "tool_calls_log": [],
                            })
                            service._get_graph = MagicMock(return_value=graph)
                            service._check_cost_limits = AsyncMock()
                            service._record_cost = AsyncMock()
                            service._persist_messages = AsyncMock()
                            service._generate_follow_up_questions = AsyncMock(return_value=[])

                            with patch("app.services.audit_service.log_event", new=AsyncMock()):
                                with patch("app.services.agent_service.parse_citations", return_value=[]):
                                    with patch("app.services.agent_service.build_citation_info", return_value=[]):
                                        result = await service.chat(1, "问题", 1)

                            assert "没有找到相关信息" in result.answer


class TestBuildGraphForStream:
    """_build_graph_for_stream 图构造"""

    def test_build_graph_for_stream_react(self, service):
        with patch("app.services.agent_service.settings") as mock_settings:
            mock_settings.AGENT_MAX_TOOL_ITERATIONS = 5
            with patch("app.agent.graph_react.create_react_graph") as mock_create:
                mock_graph = MagicMock()
                mock_graph.compile = MagicMock(return_value=MagicMock())
                mock_create.return_value = mock_graph
                with patch.object(service, "_build_tools", return_value=[MagicMock()]):
                    service._build_graph_for_stream(MagicMock(), "m", None, react_mode=True)
                mock_create.assert_called_once()


class TestHelpers:
    """其他公共 helper"""

    def test_truncate_history_keeps_system_and_last_user(self, service):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        result = service._truncate_history(messages, max_rounds=10, max_tokens=100000)
        assert result[0]["role"] == "system"
        assert result[-1]["content"] == "q2"

    def test_truncate_history_detects_reference_words(self, service):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "刚才那个再说说"},
        ]
        result = service._truncate_history(messages, max_rounds=1, max_tokens=100000)
        # 指代词触发保留更多轮次
        assert len(result) >= 2

    def test_orm_msg_to_dict_accepts_dict(self, service):
        assert service._orm_msg_to_dict({"role": "user", "content": "hi"}) == {"role": "user", "content": "hi"}

    def test_conv_messages_to_llm_messages_filters_tool_calls(self, service):
        raw = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "t1"},
            {"role": "system", "content": "sys"},
        ]
        result = service._conv_messages_to_llm_messages(raw)
        assert len(result) == 4
        assert "tool_calls" not in result[1]
        assert result[2]["role"] == "tool"

    @pytest.mark.asyncio
    async def test_prepare_stream_context_creates_conversation(self, service):
        with patch("app.services.agent_service.KBService") as MockKB:
            MockKB.return_value.get_accessible = AsyncMock(
                return_value=MagicMock(system_prompt="")
            )
            with patch("app.services.agent_service.ConversationService") as MockConv:
                mock_conv = MagicMock()
                mock_conv.id = 7
                MockConv.return_value.create = AsyncMock(return_value=mock_conv)
                MockConv.return_value.get = AsyncMock()
                with patch("app.services.agent_service.MessageRepository") as MockMsg:
                    MockMsg.return_value.list_by_conversation = AsyncMock(return_value=([], 0))
                    with patch("app.services.agent_service.settings") as mock_settings:
                        mock_settings.CHECKPOINT_ENABLED = False
                        ctx = await service._prepare_stream_context(1, "q", 1, None)

        assert ctx.conv_id == 7
        assert ctx.is_new_conversation is True
        assert ctx.question == "q"
        MockConv.return_value.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_build_tools_registers_retrieve(self, service):
        service.kb_id = 1
        service.user_id = 1
        with patch("app.services.agent_service.create_retrieve_knowledge_tool") as mock_create:
            with patch("app.services.agent_service.settings") as mock_settings:
                mock_settings.REACT_ENABLED = False
                mock_create.return_value = MagicMock(name="retrieve")
                tools = service._build_tools()
                assert len(tools) == 1
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_tools_adds_kb_info_when_react_enabled(self, service):
        service.kb_id = 1
        service.user_id = 1
        with patch("app.services.agent_service.create_retrieve_knowledge_tool") as mock_retrieve:
            with patch("app.services.agent_service.create_kb_info_tool") as mock_kb_info:
                with patch("app.services.agent_service.settings") as mock_settings:
                    mock_settings.REACT_ENABLED = True
                    mock_retrieve.return_value = MagicMock(name="retrieve")
                    mock_kb_info.return_value = MagicMock(name="kb_info")
                    tools = service._build_tools()
                    assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_generate_follow_up_returns_questions(self, service):
        response = MagicMock(choices=[MagicMock(message=MagicMock(content="问题1\n问题2？\n无关长文本"))])
        service.llm_client.chat.completions.create = AsyncMock(return_value=response)
        questions = await service._generate_follow_up_questions("q", "a" * 30)
        assert len(questions) <= 3
        assert all(len(q) <= 60 for q in questions)

    @pytest.mark.asyncio
    async def test_generate_follow_up_returns_empty_on_short_answer(self, service):
        assert await service._generate_follow_up_questions("q", "short") == []

    @pytest.mark.asyncio
    async def test_persist_messages_creates_user_and_assistant(self, service):
        msg_repo = MagicMock()
        msg_repo.create = AsyncMock()
        conv_service = MagicMock()
        conv_service.conv_repo.increment_message_count = AsyncMock()

        await service._persist_messages(
            msg_repo, conv_service, 1, "q", "a",
            [{"tool": "t", "input": {}, "output": "o"}],
            [{"chunk_id": 1}], 5, follow_up_questions=["fq"],
        )

        assert msg_repo.create.await_count == 2
        calls = msg_repo.create.await_args_list
        assert calls[0][0][0]["role"] == "user"
        assert calls[1][0][0]["role"] == "assistant"
        assert calls[1][0][0]["token_count"] == 5


# ── helpers ──

async def async_iter(items):
    for item in items:
        yield item


def extract_event(frame: str) -> str:
    """从 SSE frame 中提取 event 类型；无 event 行返回空字符串（data-only）。"""
    for line in frame.split("\n"):
        if line.startswith("event:"):
            return line[6:].strip()
    return ""


def _base_ctx_fixture(service):
    ctx = _StreamContext(
        conv_id=1,
        is_new_conversation=True,
        question="q",
        all_messages=[],
        initial_state={},
        config={},
        checkpointer=None,
        msg_repo=MagicMock(),
        conv_service=MagicMock(),
        tools=[],
    )
    return ctx
