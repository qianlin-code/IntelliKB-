# IntelliKB Phase 5 — 体验增强：Token 流式 + RAG 评测 + 完整 ReAct

> **目标路径**：本规划在评审通过后应作为 `docs/phase5-plan.md` 保存。
>
> **修订记录**：
> - v1（初稿）：B1 generator 方案
> - v2：P0 改为 Option C（双 graph + aupdate_state）；eval API 权限校验；ReAct 裸 OpenAI client；get_llm_client 返回 tuple
> - v3：P0 改为方案 A（单 graph + interrupt_before）；REACT/STREAMING 叠加规则；create_agent_graph 签名对齐；nodes.py 抽取；config 云端校验；C1 重启验证
> - v4（最终版）：P0 改为 interrupt_after；新增 C0 前置验证；chat() 路径独立；isinstance 修正；EMBEDDING_TIMEOUT_SECONDS；C1 改用 chat-stream

---

## 1. 背景与目标

Phase 4 交付了 Checkpointer 持久化、前端 Markdown/搜索/导出、KBMember 缓存接入、语义标题等质量增强能力。当前系统在功能完整性上已覆盖「知识库管理 → 文档上传 → 混合检索 → RAG 问答 → Agent 对话」全链路，但存在三个体验/质量短板：

- **Agent 回答不是打字机效果** — `call_model` 节点完成后一次性输出全部文本，用户需等待 3-10 秒后才能看到内容，交互感知延迟高。
- **检索质量无量化反馈** — 无法回答"检索效果好不好"、"模型升级后提升了多少"等问题，缺少持续优化的数据基础。
- **Agent 架构过于简单** — 硬编码 `retrieve_knowledge → call_model → end` 两阶段流程，无法利用 LLM tool-choice 能力做多步推理、交叉验证、动态工具选择。

Phase 5 定位于**「体验增强 + 质量闭环 + 架构升级」**，三项能力按优先级递进：先做用户可感知的 token 流式（P0），再建检索质量基线（P1），最后在基线之上做完整 ReAct 架构升级（P2）。

---

## 2. 范围边界

| 优先级 | 功能 | 一句话描述 |
|:------:|------|------|
| **P0** | Token 级流式 | 单 graph + interrupt_after + 直接 LLM stream=True + aupdate_state，逐 token SSE |
| **P1** | RAG 评测量表·轻量版 | 自动合成查询集 + Hit Rate@k / MRR / Recall@k + 前端指标展示 |
| **P2** | 完整 ReAct 多工具 + 模型策略 | call_model → should_continue → call_tool 循环；至少 2 个工具；支持本地/云端模型切换 |

### 明确不包含（延后 Phase 6 或标记为可选）

| 方向 | 延后原因 |
|------|----------|
| D1: 文档预处理增强（语义分块、metadata 提取） | 与 Phase 5 核心目标无直接关联 |
| D2: 答案质量用户反馈（点赞/踩 → 检索权重） | 依赖 P1 评测体系建立后才能衡量效果 |
| D3: 多 KB 联合检索 | 需先稳定单 KB 检索质量 |
| D4: 对话级工具扩展（文档列表、日期筛选等） | P2 ReAct 框架预留扩展点，具体工具延后 |
| D5: Token 流式断线重连恢复 | 前端 useSSE 已预留 Last-Event-ID，后端事件回放延后 |

### 配置开关总览

| 开关 | 默认值 | 行为 |
|------|:------:|------|
| `STREAMING_TOKEN_LEVEL` | `True` | `True`=逐 token SSE 推送（方案 A）；`False`=节点级一次性输出（降级） |
| `RAG_EVAL_ENABLED` | `True` | `True`=注册 `/eval` 路由；`False`=路由不注册，请求返回 404 |
| `REACT_ENABLED` | `False`（开发初期） | `True`=完整 ReAct 循环；`False`=走 Phase 4 简化两阶段 |

> **ReAct 初期默认 `False`**：在模型选型验证通过后，通过配置切换为 `True`。简化两阶段作为永久的 fallback 路径保留。

**配置开关叠加规则**：

```
┌──────────────────────────────────────────────────────────────────┐
│ REACT_ENABLED 与 STREAMING_TOKEN_LEVEL 叠加行为                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  REACT_ENABLED=true 时：                                          │
│    → STREAMING_TOKEN_LEVEL 自动失效（被忽略）                       │
│    → ReAct 循环内部涉及多次 LLM 调用，token 级流式无意义，          │
│      统一使用节点级 astream 输出                                   │
│    → chat_stream() 走 graph_react 路径 + 节点级 yield              │
│                                                                   │
│  REACT_ENABLED=false 时：                                         │
│    → STREAMING_TOKEN_LEVEL=true  → 方案 A（单 graph +              │
│      interrupt_after + 直接 LLM stream + aupdate_state）           │
│    → STREAMING_TOKEN_LEVEL=false → Phase 4 节点级输出（降级）      │
│                                                                   │
│  chat()（非流式）永远不受 STREAMING_TOKEN_LEVEL 影响：              │
│    → 始终使用非 interrupt 的 graph.ainvoke()，与 Phase 4 行为一致  │
│    → 理由：非流式不需要逐 token 控制，interrupt/resume 无必要       │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 现状盘点

| 维度 | Phase 4 完成时状态 |
|------|-------------------|
| Agent 架构 | 硬编码两阶段：`call_tool(retrieve_knowledge)` → `call_model` → `end`，不走 LLM tool-choice |
| 工具集 | 仅 `retrieve_knowledge` 启用；`get_kb_info` 已实现但注释掉 |
| 模型 | qwen2.5:7b via Ollama；代码注释明确标注 function calling 不稳定 |
| LLM 客户端 | `get_llm_client(purpose)` 统一工厂，返回 `AsyncOpenAI`，支持 default / agent / embed 三种用途 |
| 流式粒度 | **节点级** `astream(stream_mode="updates")`，call_model 完成后一次性输出；SSE 推送的是节点间 delta |
| 检索管线 | BM25 + Vector + RRF + Rerank + Redis Cache（成熟，Phase 2） |
| Checkpointer | MySQL 持久化（Phase 4，稳定），`CHECKPOINT_ENABLED` 可热切换 |
| 前端 SSE | `useSSE.ts` 统一 composable；`AgentStreamRenderer` 已支持追加模式（`streamContent += data`） |
| 前端 Markdown | `useMarkdown.ts` 统一渲染，marked + hljs + DOMPurify |
| 评测基础设施 | **零** — 无测试查询集、无指标计算、无可视化 |
| 数据库迁移 | phase4_001 (head)，`sys_agent_checkpoint` 表稳定运行 |

---

## 4. 技术决策

### D1: Token 流式方案

**问题根因分析**：LangGraph 的 generator 节点在 `astream(stream_mode="updates")` 下，每次 `yield` 不会单独触发 stream event——generator 内部 yield 的值在节点内累积，最终通过 `return` 一次性输出。因此"在 call_model 节点内 yield token"的方案（原 B1）**不可行**。

**方案 A: 单 graph + interrupt_after（最终版）**

使用 LangGraph 的 `interrupt_after` 机制：graph 执行完 call_tool 节点后自动暂停，Checkpointer 已持久化检索结果。然后在 `chat_stream()` 层面手动 LLM stream，token 输出完成后通过同一 graph 实例的 `aupdate_state` 写入最终答案。

```
编译: graph.compile(checkpointer=ck, interrupt_after=["call_tool"])
执行: graph.ainvoke(initial_state, config)
       → call_tool 执行完毕 → Checkpointer 自动持久化 → 暂停 ⏸
手动: llm_client.chat.completions.create(stream=True)
       → 逐 token yield SSE data: 帧
写入: 同一个 graph.aupdate_state(config, values)
       → Checkpointer 追加最终 answer checkpoint
```

**为什么用 `interrupt_after` 而非 `interrupt_before`**：

| 机制 | 暂停时机 | 状态内容 | 优势 |
|------|---------|---------|------|
| `interrupt_after=["call_tool"]` | call_tool **执行完毕后** | state 自然包含 call_tool 的全部输出（messages + sources + tool_calls_log） | 语义清晰：工具调用已完整完成，下一个动作就是写入 LLM 答案 |
| `interrupt_before=["call_model"]` | call_model **执行前** | 同上（call_tool 已完成，call_model 未开始） | 效果等价，但 "before call_model" 容易产生"还需要运行 call_model" 的误解 |

选择 `interrupt_after=["call_tool"]`：call_tool 节点已完整执行且 checkpoint 已持久化，aupdate_state 后无残留的 "待执行节点" 状态，语义更干净。

**中断残留问题说明**：`interrupt_after` 暂停后调用 `aupdate_state` 写入 assistant message，下轮对话 `ainvoke` 时 LangGraph 从 interrupt 点恢复。由于已通过 `aupdate_state` 更新了 state，且 graph 在 call_tool 之后、END 之前无其他节点，下轮 `ainvoke` 会从 call_tool 的输出边继续（即抵达 END），不会触发 call_model 的重复执行。此行为在实现前通过 C0 前置验证确认（见 §8）。

| 方案 | 做法 | 优势 | 劣势 | 结论 |
|------|------|------|------|:----:|
| **方案 A: interrupt_after** | 编译时传入 `interrupt_after=["call_tool"]`，graph.ainvoke 执行 call_tool 后自动暂停，手动 LLM stream 完成后通过**同一 graph 实例**的 aupdate_state 写入 | 全程单 graph 实例，checkpoint 一致性由 LangGraph 保证；语义清晰（工具调用已完整完成） | 需 C0 验证中断后 aupdate_state + 下轮 ainvoke 的行为 | **✅ 推荐** |
| 方案 B: 双 graph | tool_graph 和 full_graph 两个编译实例 | 无 | 跨 graph 实例 aupdate_state 存在 checkpoint 不一致风险 | ❌ |
| Option B: astream_events v2 | LangGraph 原生 token 流式 | LangGraph 原生支持 | 需引入 langchain-openai 依赖，与项目裸客户端哲学矛盾 | ❌ |

**决策 D1**：采用**方案 A（单 graph + interrupt_after + C0 前置验证）**。编码前先编写独立测试脚本验证 `ainvoke → interrupt_after → aupdate_state → 下轮 ainvoke` 的完整行为，确认通过后再进入正式编码。

**完整时序**：

```
┌─────────────────────────────────────────────────────────────────┐
│ chat_stream()  token 级流式 (STREAMING_TOKEN_LEVEL=True,         │
│                             REACT_ENABLED=False)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. 编译 graph（单实例，全程复用）                                  │
│     graph = create_agent_graph(tools)                            │
│     compiled = graph.compile(                                    │
│         checkpointer=checkpointer,                               │
│         interrupt_after=["call_tool"],  ← 关键                    │
│     )                                                            │
│                                                                  │
│  2. graph.ainvoke(initial_state, config)                         │
│     ┌──────────────────────────────────────────┐                 │
│     │ call_tool 节点                             │                 │
│     │   ├─ retrieve_knowledge.ainvoke(question)  │                 │
│     │   └─ INSERT sys_agent_checkpoint           │  ← Checkpointer │
│     │      (type='checkpoint')                   │     自动持久化   │
│     └──────────────────────────────────────────┘                 │
│     → LangGraph 在 call_tool 执行完毕后暂停 ⏸                      │
│     → 返回值 state 含 messages + sources + tool_calls_log        │
│                                                                  │
│  3. emit SSE: thought, tool_call, tool_result, sources           │
│                                                                  │
│  4. 直接 LLM stream（裸 AsyncOpenAI）                              │
│     response = await llm_client.chat.completions.create(         │
│         model=model_name, messages=api_messages,                 │
│         stream=True,                                             │
│     )                                                            │
│     async for chunk in response:                                 │
│         delta = chunk.choices[0].delta                           │
│         if delta.content:                                        │
│             collected_answer += delta.content                    │
│             yield f"data: {json.dumps(delta.content)}\n\n"       │
│                                                                  │
│  5. 同一 graph 实例 aupdate_state                                 │
│     await compiled.aupdate_state(  ← 同一个 compiled 实例          │
│         config,                                                  │
│         {"messages": [{"role": "assistant",                      │
│                        "content": collected_answer}],            │
│          "sources": all_sources,                                 │
│          "tool_calls_log": all_tool_calls},                      │
│     )                                                            │
│     → INSERT sys_agent_checkpoint (type='checkpoint')            │
│     → 预期 graph 从 interrupt 点继续执行；call_model 是否会被重复触发      │
│       由 C0 前置验证确认。若 C0 发现重复执行，按 §8 降级方案处理            │
│                                                                  │
│  6. persist messages + semantic title（同 Phase 4）               │
│                                                                  │
│  chat()（非流式）不受影响：                                        │
│    → 始终编译时不传 interrupt_after，走普通 ainvoke 路径            │
│    → call_tool → call_model → end 一气呵成                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**降级路径**：

```
STREAMING_TOKEN_LEVEL=False → 编译时不传 interrupt_after
                            → graph.astream(stream_mode="updates")
                            → Phase 4 节点级输出，行为完全不变

REACT_ENABLED=True          → STREAMING_TOKEN_LEVEL 被忽略
                            → 走 graph_react + 节点级 astream

chat()（非流式）             → 永远不传 interrupt_after
                            → 始终走普通 graph.ainvoke()
```

---

### D2: RAG 评测数据集生成方案

| 方案 | 做法 | 质量 | 成本 | 结论 |
|------|------|:----:|:----:|:----:|
| **v1: 自动合成** | 从文档随机抽取段落 → LLM 生成对应问题 → 原文档作为 ground truth | 中（需人工抽检） | 低（自动化） | **✅ v1 推荐** |
| v2: 人工标注 | 手动标注 50-100 条查询-文档对 | 高 | 高（人力） | 延后 |
| v3: 用户行为弱标注 | 收集用户点击/点赞 → 隐式反馈 | 低但真实 | 零 | 延后 |

**决策 D2**：v1 使用自动合成，v2/v3 延后。

理由：
1. Phase 5 的评测目标是建立**相对比较基线**（如"模型升级前 vs 升级后的 MRR"），而非绝对精度。自动合成的偏差对相对比较影响较小。
2. 不需要额外的人力投入，可在 2-3 个知识库上一键生成评测集。
3. 后续可逐步加入人工抽检（对合成结果抽样验证）和用户行为信号。

**合成流程**：
```
文档段落（随机抽取 50-200 段）
  → LLM prompt：「根据以下段落生成一个用户可能提出的问题。
                 只返回问题本身，不要额外文字。」
  → 生成问题列表
  → 评测集: [{question, relevant_doc_ids: [原文档ID], relevant_chunk_ids: [原段落ID]}]
```

**评测指标定义**：

| 指标 | 公式 | 含义 |
|------|------|------|
| Hit Rate@k | Σ(问题在被检索到的 top-k 中至少包含 1 个相关文档) / N | 覆盖率 |
| MRR | (1/N) · Σ(1 / 第一个相关文档的排名) | 首个相关文档的排序质量 |
| Recall@k | Σ(top-k 中相关文档数 / 总相关文档数) / N | 召回完整性 |

**前端展示**：简单数字卡片 + 表格，不引入 ECharts 等重量图表库。

---

### D3: ReAct 模型策略

| 维度 | 本地 Ollama | 云端 API |
|------|------------|---------|
| function calling 稳定性 | 依赖模型能力（7b 不稳定，14b+ 改善） | 成熟稳定（DeepSeek / 通义千问 / GPT） |
| 成本 | 零 API 费用（硬件 + 电费） | 按 token 计费 |
| 延迟 | 取决于 GPU | 网络 + 云端推理 |
| 隐私 | 数据不出本机 | 数据出境（需评估合规） |
| 运维 | 需自行管理模型服务 | 零运维 |

**决策 D3**：
1. **架构同时支持本地和云端** — 配置层抽象 model provider，通过 `.env` 变量切换。
2. **开发阶段默认使用本地模型** — 降低成本，无网络依赖。
3. **云端作为可选升级路径** — 当本地模型 function calling 不满足需求时，切换云端仅需修改 `.env`。
4. **有评测基线后再切换** — P1 的评测指标可用于量化「本地→云端」的检索质量提升。

**候选模型对比表**：

| 模型 | 部署方式 | 显存要求 | Function Calling | 中文能力 | 备注 |
|------|:------:|:--------:|:----------------:|:--------:|------|
| qwen2.5:7b | Ollama 本地 | ~5GB | ⚠️ 不稳定 | ★★★★ | 当前使用 |
| qwen2.5:14b | Ollama 本地 | ~9GB | ✅ 可用 | ★★★★☆ | **本地首选升级目标** |
| qwen2.5:32b | Ollama 本地 | ~20GB | ✅ 稳定 | ★★★★★ | 需高端 GPU |
| deepseek-r1:8b | Ollama 本地 | ~5GB | ⚠️ 一般 | ★★★☆ | 推理模型，速度慢 |
| deepseek-chat | 云端 API | — | ✅ 成熟 | ★★★★★ | ¥1/百万 token |
| qwen-turbo | 云端 API | — | ✅ 成熟 | ★★★★★ | 阿里云，¥0.3/百万 token |
| gpt-4o-mini | 云端 API | — | ✅ 最稳定 | ★★★★ | ¥1/百万 token，数据出境 |

**配置设计**：

```python
# app/config.py 新增
# ── Phase 5: 模型 Provider ──
LLM_PROVIDER: str = "ollama"  # ollama | deepseek | qwen | openai
# 本地模型（LLM_PROVIDER=ollama 时生效）
LLM_MODEL_NAME: str = "qwen2.5:7b"
AGENT_MODEL: str = "qwen2.5:7b"
# 云端模型（LLM_PROVIDER=deepseek/qwen/openai 时使用各 provider 的 base_url + model）
CLOUD_MODEL_NAME: str = "deepseek-chat"        # 非 Agent 场景
CLOUD_AGENT_MODEL: str = "deepseek-chat"       # Agent 场景（需 function calling）
CLOUD_BASE_URL: str = ""
CLOUD_API_KEY: str = ""
```

> **关于 `AGENT_MAX_TOOL_ITERATIONS`**：此配置项在 Phase 3 已定义（`app/config.py:136`，默认值 `5`），Phase 5 在 `create_react_graph()` 中作为 `max_iterations` 参数使用，不再新增。

---

### D4: 工具注册机制

| 方案 | 做法 | 优势 | 劣势 | 结论 |
|------|------|------|------|:----:|
| **硬编码列表 + 闭包注入** | 在 `AgentService._build_tools()` 中维护工具列表，通过闭包注入 db/kb_id/user_id | 简单直观，与当前架构一致 | 新增工具需修改 `_build_tools()` | ✅ **Phase 5 推荐** |
| 动态注册表 | 维护全局 `TOOL_REGISTRY` dict，工具函数按名称注册 | 扩展性好 | 过度设计（当前仅 2-3 个工具）；全局状态管理复杂 | ❌ |

**决策 D4**：保留当前硬编码列表 + 闭包注入模式，在 `_build_tools()` 中按 `REACT_ENABLED` 决定注册哪些工具。

```python
def _build_tools(self):
    """Phase 5: 根据 REACT_ENABLED 决定工具集"""
    tools = [
        create_retrieve_knowledge_tool(self.db, self.kb_id, self.user_id),
    ]
    if settings.REACT_ENABLED:
        tools.append(create_kb_info_tool(self.db, self.kb_id, self.user_id))
        # 未来工具在此追加
    return tools
```

---

### D5: get_llm_client 返回模型名

**问题**：当前 `get_llm_client(purpose)` 只返回 `AsyncOpenAI` 客户端，调用方自行从 `settings.LLM_MODEL_NAME` / `settings.AGENT_MODEL` 取模型名。引入多 provider 后，不同 provider 使用不同模型名（如 ollama 用 `qwen2.5:7b`，deepseek 用 `deepseek-chat`），调用方需要感知 provider 差异。

**决策 D5**：`get_llm_client(purpose)` 改为返回 `tuple[AsyncOpenAI, str]`，同时返回客户端和模型名。`lru_cache(maxsize=4)` 基于函数参数 `purpose` 做缓存——缓存键为 `purpose` 字符串，与返回值类型无关。

---

### D6: call_tool 节点逻辑抽取

**问题**：`graph.py` 中的 `call_tool` 节点逻辑需要在 token 流式路径中构建 LLM messages 时引用其输出格式，但 P0 方案 A 不再需要独立编译 tool-only graph。

**决策 D6**：将 `call_tool` 节点逻辑抽取到 `app/agent/nodes.py`，`graph.py` 直接引用。P0 token 流式路径中的 LLM messages 构建复用 `graph.py` 已有的 `_lc_message_to_dict` 函数，无需维护两份 `call_tool` 代码。

```python
# app/agent/nodes.py（新增）
def create_call_tool_node(tool_map: dict):
    """创建 call_tool 节点（供 graph.py 引用）"""
    async def call_tool(state: AgentState) -> dict:
        # ... 原 graph.py 中 call_tool 的完整逻辑 ...
    return call_tool
```

---

## 5. 后端变更

### 5.1 P0: Token 级流式（方案 A — interrupt_after）

#### 5.1.1 新增 `app/agent/nodes.py`

从 `graph.py` 中抽取公共 `call_tool` 节点逻辑。

```python
"""
Agent Graph 公共节点（Phase 5）

抽取 call_tool 节点逻辑，供 graph.py 引用。
"""
import json
import logging

from app.agent.graph import AgentState

logger = logging.getLogger("app")


def create_call_tool_node(tool_map: dict):
    """创建 call_tool 节点（闭包注入 tool_map）"""

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
            logger.error("retrieve_knowledge not found in tool_map")
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
```

#### 5.1.2 修改 `app/agent/graph.py`

将 `call_tool` 节点改为引用 `nodes.py` 中的公共实现，并增加 `max_iterations` 参数以对齐签名。

```python
# app/agent/graph.py — 修改 call_tool 节点定义

from app.agent.nodes import create_call_tool_node

def create_agent_graph(llm_client, tools: list, model_name: str, max_iterations: int = 5):
    """
    创建简化两阶段 Agent Graph（Phase 3/4 行为）。

    Phase 5: 新增 max_iterations 参数，与 create_react_graph 签名对齐。
    简化两阶段不使用此参数，仅为签名对齐预留。
    """
    tool_map = {t.name: t for t in tools}
    logger.info("Agent graph created: %d tools, model=%s", len(tools), model_name)

    # ... SYSTEM_PROMPT 不变 ...

    call_tool = create_call_tool_node(tool_map)  # ← 引用 nodes.py 公共节点

    async def call_model(state: AgentState) -> dict:
        """Step 2: 基于检索结果生成回答（非流式，Phase 4 行为不变）"""
        # ... 现有逻辑完全不变 ...

    workflow = StateGraph(AgentState)
    workflow.add_node("call_tool", call_tool)
    workflow.add_node("call_model", call_model)
    workflow.set_entry_point("call_tool")
    workflow.add_edge("call_tool", "call_model")
    workflow.add_edge("call_model", END)

    return workflow  # 返回未编译的 StateGraph
```

#### 5.1.3 修改 `app/services/agent_service.py` — `chat_stream()`

核心改动：根据 `REACT_ENABLED` 和 `STREAMING_TOKEN_LEVEL` 选择三条路径。

```python
# app/services/agent_service.py — chat_stream() Phase 5 v4

async def chat_stream(self, kb_id: int, question: str, user_id: int,
                      conv_id: int | None = None,
                      background_tasks=None):
    # ── 前置逻辑不变（权限校验、对话创建、历史装载、initial_state 构建）──
    # ... (同 Phase 4) ...

    from app.agent.checkpointer import MySQLCheckpointSaver
    from app.core.database import async_session_factory
    from app.config import settings
    from app.agent.graph import AgentState, create_agent_graph, _lc_message_to_dict

    checkpointer = (
        MySQLCheckpointSaver(async_session_factory)
        if settings.CHECKPOINT_ENABLED
        else None
    )
    config = {"configurable": {"thread_id": f"conv:{conv_id}"}}

    collected_answer = ""
    all_sources: list[dict] = []
    all_tool_calls: list[dict] = []

    tools = self._build_tools()

    # ═══════════════════════════════════════════════════════════
    # 路径选择
    # ═══════════════════════════════════════════════════════════

    if settings.REACT_ENABLED:
        # ── 路径 1: ReAct 模式 → 节点级输出（STREAMING_TOKEN_LEVEL 被忽略）──
        from app.agent.graph_react import create_react_graph

        graph = create_react_graph(
            llm_client=self.llm_client,
            tools=tools,
            model_name=self.llm_model,
            max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
        ).compile(checkpointer=checkpointer)

        prev_sent_len = 0
        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
            # ... Phase 4 节点级流式逻辑，完全不变 ...
            pass

    elif settings.STREAMING_TOKEN_LEVEL:
        # ── 路径 2: 方案 A — interrupt_after + 直接 LLM stream + aupdate_state ──

        # Step 1: 编译 graph（interrupt_after 在 call_tool 完成后暂停）
        graph = create_agent_graph(
            llm_client=self.llm_client,
            tools=tools,
            model_name=self.llm_model,
        )
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_after=["call_tool"],  # ← call_tool 执行完毕后暂停
        )

        # Step 2: ainvoke 执行 call_tool → 暂停
        yield f"event: thought\ndata: {json.dumps({'content': '正在检索相关知识...'}, ensure_ascii=False)}\n\n"

        tool_state = await compiled.ainvoke(initial_state, config)
        # → call_tool 完整执行，checkpoint 已持久化，graph 在 call_tool 后暂停

        all_tool_calls = tool_state.get("tool_calls_log", [])
        all_sources = tool_state.get("sources", [])

        # Emit tool_call / tool_result / sources
        yield (
            f"event: tool_call\n"
            f"data: {json.dumps({'tool': 'retrieve_knowledge', 'input': {'question': question[:100]}}, ensure_ascii=False)}\n\n"
        )
        chunk_count = len(all_sources)
        yield (
            f"event: tool_result\n"
            f"data: {json.dumps({'tool': 'retrieve_knowledge', 'output': f'检索到 {chunk_count} 条结果', 'chunk_count': chunk_count}, ensure_ascii=False)}\n\n"
        )
        if all_sources:
            yield f"event: sources\ndata: {json.dumps({'sources': all_sources}, ensure_ascii=False)}\n\n"

        # Step 3: 构建 LLM messages + 直接 stream
        from langchain_core.messages import SystemMessage
        from app.agent.graph import SYSTEM_PROMPT

        llm_messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for m in tool_state.get("messages", []):
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                tc_id = m.get("tool_call_id", "")
                if role == "tool":
                    llm_messages.append({
                        "role": "tool", "content": content, "tool_call_id": tc_id,
                    })
                elif role in ("user", "assistant", "system"):
                    llm_messages.append({"role": role, "content": content})

        api_messages = [_lc_message_to_dict(m) for m in llm_messages]

        stream = await self.llm_client.chat.completions.create(
            model=self.llm_model,
            messages=api_messages,
            temperature=0.3,
            max_tokens=2048,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                collected_answer += delta.content
                yield f"data: {json.dumps(delta.content, ensure_ascii=False)}\n\n"

        # Step 4: 同一 graph 实例 aupdate_state
        await compiled.aupdate_state(
            config,
            {
                "messages": [{"role": "assistant", "content": collected_answer}],
                "sources": all_sources,
                "tool_calls_log": all_tool_calls,
            },
        )
        # → checkpoint 写入最终答案；预期 graph 从 interrupt 点继续执行
        # （call_model 是否会被重复触发由 C0 前置验证确认，若失败按 §8 降级处理）

    else:
        # ── 路径 3: 节点级输出（Phase 4 降级，完全不变）──
        graph = create_agent_graph(
            llm_client=self.llm_client,
            tools=tools,
            model_name=self.llm_model,
        ).compile(checkpointer=checkpointer)

        prev_sent_len = 0
        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
            # ... Phase 4 逻辑完全不变 ...
            pass

    # ── 后续逻辑不变（persist + done + 语义标题）──
    # ... (同 Phase 4) ...
```

**路径总结**：

| REACT_ENABLED | STREAMING_TOKEN_LEVEL | 执行路径 | 流式粒度 |
|:------------:|:--------------------:|---------|:------:|
| `True` | 任意（被忽略） | 路径 1: graph_react.astream(updates) | 节点级 |
| `False` | `True` | 路径 2: 方案 A interrupt_after + LLM stream | **token 级** |
| `False` | `False` | 路径 3: graph.astream(updates)（Phase 4） | 节点级 |

#### 5.1.4 修改 `app/config.py`

```python
# ── Phase 5: Token 流式 ──
STREAMING_TOKEN_LEVEL: bool = True  # True=方案 A 逐 token SSE；False=节点级降级
# 注意：
#   1. REACT_ENABLED=true 时本开关自动失效（见 §2 叠加规则）
#   2. chat()（非流式）永远不读本开关，始终走非 interrupt 路径

# ── Phase 5: Embedding 超时 ──
EMBEDDING_TIMEOUT_SECONDS: float = 60.0  # embedding 请求超时（秒），替代 llm_client.py 中的硬编码 60.0
```

#### 5.1.5 云端 API Key 启动校验

```python
# app/config.py — 在现有 _validate_security 中追加 Phase 5 校验

@model_validator(mode="after")
def _validate_security(self):
    # ... 现有 SECRET_KEY / DB_PASSWORD / ADMIN_PASSWORD 校验不变 ...

    # Phase 5: 云端 provider 必须提供 API Key
    if self.LLM_PROVIDER != "ollama" and not self.CLOUD_API_KEY:
        raise ValueError(
            f"LLM_PROVIDER={self.LLM_PROVIDER} 但 CLOUD_API_KEY 为空。"
            f"请在 .env 中设置 CLOUD_API_KEY，或切换回 LLM_PROVIDER=ollama。"
        )

    return self
```

#### 5.1.6 `chat()`（非流式）路径

`chat()` 永远不受 `STREAMING_TOKEN_LEVEL` 影响——始终使用普通的 `graph.compile(checkpointer=checkpointer)`（不传 `interrupt_after`），走 `graph.ainvoke()` 完整执行 `call_tool → call_model → end`。

```python
async def chat(self, ...):
    # ...
    self.llm_client, self.llm_model = get_llm_client(purpose="agent")

    graph = create_agent_graph(
        llm_client=self.llm_client,
        tools=self._build_tools(),
        model_name=self.llm_model,
    )
    # 注意：永远不传 interrupt_after，与 Phase 4 行为一致
    compiled = graph.compile(checkpointer=checkpointer)

    final_state = await compiled.ainvoke(initial_state, config)
    # → call_tool → call_model → end 一气呵成
    # ... 后续逻辑不变 ...
```

---

### 5.2 P1: RAG 评测量表

#### 5.2.1 新增 `app/models/eval.py`

```python
"""
RAG 评测数据模型
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time_utils import utcnow
from app.models.base import Base


class EvalQuery(Base):
    """评测查询集（自动合成或人工标注）"""
    __tablename__ = "sys_eval_query"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_knowledge_base.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    relevant_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array: [1,2,3]")
    relevant_doc_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array: [1,2]")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="synthetic",
        comment="synthetic | manual"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_eval_query_kb", "kb_id"),
    )


class EvalRun(Base):
    """评测执行记录"""
    __tablename__ = "sys_eval_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_knowledge_base.id"), nullable=False, index=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="评测配置快照")
    hit_rate_at_3: Mapped[float] = mapped_column(Float, nullable=True)
    hit_rate_at_5: Mapped[float] = mapped_column(Float, nullable=True)
    mrr: Mapped[float] = mapped_column(Float, nullable=True)
    recall_at_3: Mapped[float] = mapped_column(Float, nullable=True)
    recall_at_5: Mapped[float] = mapped_column(Float, nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_eval_run_kb", "kb_id"),
        Index("idx_eval_run_kb_time", "kb_id", "created_at"),
    )


class EvalResult(Base):
    """单条查询的评测明细"""
    __tablename__ = "sys_eval_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_eval_run.id"), nullable=False, index=True)
    query_id: Mapped[int] = mapped_column(Integer, ForeignKey("sys_eval_query.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, comment="第一个相关文档的排名，0 表示未命中")
    hits_in_top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retrieved_chunk_ids: Mapped[str] = mapped_column(Text, nullable=False, comment="JSON array")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now(),
    )
```

#### 5.2.2 新增 `app/services/eval_service.py`

```python
"""
RAG 评测服务

- 自动合成查询集（从文档段落 → LLM 生成问题）
- 执行评测（遍历查询集 → 调检索管线 → 计算指标）
- 指标查询（按 KB 查历史评测结果）

依赖: HybridSearchService.search(kb_id, question, user, top_k, use_rerank, use_cache)
      返回 tuple[list[SearchResult], str | None] — (results, rewritten_query)
      该服务在 Phase 2 已实现（app/services/hybrid_search_service.py），Phase 5 直接使用。
"""
import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm_client import get_llm_client

logger = logging.getLogger("app")


class EvalService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm_client, self.llm_model = get_llm_client(purpose="default")

    async def synthesize_queries(self, kb_id: int, count: int = 50) -> int:
        """自动合成评测查询集

        1. 随机抽取 count 个 chunk
        2. 对每个 chunk 用 LLM 生成对应问题
        3. 写入 sys_eval_query
        返回生成的查询数量。
        """
        from sqlalchemy import select, func
        from app.models.document import DocumentChunk

        # MySQL: func.rand() 是 MySQL 专属随机排序函数
        # 若后续迁移到 PostgreSQL，需改为 func.random()
        result = await self.db.execute(
            select(DocumentChunk.id, DocumentChunk.content, DocumentChunk.document_id)
            .where(DocumentChunk.kb_id == kb_id)
            .order_by(func.rand())
            .limit(count)
        )
        chunks = result.all()

        generated = 0
        from app.models.eval import EvalQuery

        for chunk in chunks:
            try:
                response = await self.llm_client.chat.completions.create(
                    model=self.llm_model,
                    messages=[{
                        "role": "system",
                        "content": (
                            "根据以下文档段落生成一个用户可能提出的问题。"
                            "问题应自然、具体。只返回问题本身，不要引号或额外文字。"
                        ),
                    }, {
                        "role": "user",
                        "content": f"段落内容：{chunk.content[:500]}",
                    }],
                    max_tokens=100,
                    temperature=0.7,
                )
                question = response.choices[0].message.content.strip()

                query = EvalQuery(
                    kb_id=kb_id,
                    question=question,
                    relevant_chunk_ids=json.dumps([chunk.id]),
                    relevant_doc_ids=json.dumps([chunk.document_id]),
                    source="synthetic",
                )
                self.db.add(query)
                generated += 1
            except Exception as e:
                logger.warning("合成 query 失败 chunk=%d: %s", chunk.id, e)
                continue

        await self.db.commit()
        return generated

    async def run_evaluation(self, kb_id: int, top_k: int = 5) -> dict:
        """执行评测

        依赖 HybridSearchService.search() 接口：
        - 签名: search(kb_id, question, user, top_k, use_rerank, use_cache)
        - 返回: tuple[list[SearchResult], str | None]
        - 该服务在 Phase 2 已实现（app/services/hybrid_search_service.py），Phase 5 直接使用
        """
        from sqlalchemy import select
        from app.models.eval import EvalQuery, EvalRun, EvalResult
        from app.services.hybrid_search_service import HybridSearchService
        from app.repositories.user import UserRepository

        result = await self.db.execute(
            select(EvalQuery).where(EvalQuery.kb_id == kb_id)
        )
        queries = result.scalars().all()

        if not queries:
            raise ValueError(f"知识库 {kb_id} 无评测查询，请先执行 synthesize_queries")

        user_repo = UserRepository(self.db)
        from app.models.knowledge_base import KnowledgeBase
        kb_result = await self.db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = kb_result.scalar_one_or_none()
        if kb is None:
            raise ValueError(f"知识库 {kb_id} 不存在")
        user = await user_repo.get_by_id(kb.owner_id)

        hybrid_service = HybridSearchService(self.db)

        run = EvalRun(kb_id=kb_id, query_count=len(queries))
        self.db.add(run)
        await self.db.flush()

        total_rank_sum = 0.0
        hit_count_3 = 0
        hit_count_5 = 0
        relevent_3_sum = 0.0
        relevent_5_sum = 0.0

        for query in queries:
            relevant_docs = set(json.loads(query.relevant_doc_ids))

            t0 = time.perf_counter()
            try:
                results, _ = await hybrid_service.search(
                    kb_id=kb_id,
                    question=query.question,
                    user=user,
                    top_k=top_k,
                    use_rerank=True,
                    use_cache=False,
                )
            except Exception as e:
                logger.warning("评测 search 失败 query=%d: %s", query.id, e)
                results = []
            latency_ms = int((time.perf_counter() - t0) * 1000)

            retrieved_doc_ids = [r.document_id for r in results]

            first_rank = 0
            for i, doc_id in enumerate(retrieved_doc_ids, 1):
                if doc_id in relevant_docs:
                    first_rank = i
                    break

            if first_rank > 0:
                total_rank_sum += 1.0 / first_rank
                if first_rank <= 3:
                    hit_count_3 += 1
                if first_rank <= 5:
                    hit_count_5 += 1

            hits_3 = len(set(retrieved_doc_ids[:3]) & relevant_docs)
            hits_5 = len(set(retrieved_doc_ids[:5]) & relevant_docs)
            relevent_3_sum += hits_3 / max(len(relevant_docs), 1)
            relevent_5_sum += hits_5 / max(len(relevant_docs), 1)

            detail = EvalResult(
                run_id=run.id,
                query_id=query.id,
                rank=first_rank,
                hits_in_top_k=len(set(retrieved_doc_ids[:top_k]) & relevant_docs),
                retrieved_chunk_ids=json.dumps([r.chunk_id for r in results]),
                latency_ms=latency_ms,
            )
            self.db.add(detail)

        n = len(queries)
        run.hit_rate_at_3 = round(hit_count_3 / n, 4) if n > 0 else 0.0
        run.hit_rate_at_5 = round(hit_count_5 / n, 4) if n > 0 else 0.0
        run.mrr = round(total_rank_sum / n, 4) if n > 0 else 0.0
        run.recall_at_3 = round(relevent_3_sum / n, 4) if n > 0 else 0.0
        run.recall_at_5 = round(relevent_5_sum / n, 4) if n > 0 else 0.0

        await self.db.commit()

        return {
            "run_id": run.id,
            "query_count": n,
            "hit_rate@3": run.hit_rate_at_3,
            "hit_rate@5": run.hit_rate_at_5,
            "mrr": run.mrr,
            "recall@3": run.recall_at_3,
            "recall@5": run.recall_at_5,
        }
```

#### 5.2.3 新增 `app/api/v1/eval.py`（含权限校验）

```python
"""
RAG 评测 API

Phase 5 P1: 所有端点均校验 KB 访问权限（非 KB 成员返回 403）。
RAG_EVAL_ENABLED=False 时，本路由文件不导入（请求返回 404）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import APIResponse
from app.depends.auth import get_current_user_or_api_key
from app.models.eval import EvalRun
from app.models.user import User
from app.services.eval_service import EvalService
from app.services.kb_service import KBService

router = APIRouter(prefix="/eval", tags=["RAG 评测"])


async def _require_kb_access(kb_id: int, user: User, db: AsyncSession):
    """校验 KB 访问权限：非 owner/editor/viewer → 403"""
    kb_service = KBService(db)
    await kb_service.get_accessible(kb_id, user.id)


@router.post("/queries/synthesize", summary="自动合成评测查询集")
async def synthesize_queries(
    kb_id: int,
    count: int = 50,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """自动合成评测查询集（需 KB 访问权限）"""
    await _require_kb_access(kb_id, current_user, db)
    service = EvalService(db)
    generated = await service.synthesize_queries(kb_id, count)
    return APIResponse.success(data={"generated": generated})


@router.post("/run", summary="执行评测")
async def run_eval(
    kb_id: int,
    top_k: int = 5,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """执行 RAG 评测（需 KB 访问权限）"""
    await _require_kb_access(kb_id, current_user, db)
    service = EvalService(db)
    result = await service.run_evaluation(kb_id, top_k)
    return APIResponse.success(data=result)


@router.get("/runs", summary="查询评测历史")
async def list_runs(
    kb_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user_or_api_key),
    db: AsyncSession = Depends(get_db),
):
    """查询 KB 的评测历史（需 KB 访问权限）"""
    await _require_kb_access(kb_id, current_user, db)

    total = await db.scalar(
        select(func.count(EvalRun.id)).where(EvalRun.kb_id == kb_id)
    )
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.kb_id == kb_id)
        .order_by(EvalRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs = result.scalars().all()
    return APIResponse.success(data={
        "items": [
            {
                "id": r.id, "kb_id": r.kb_id, "query_count": r.query_count,
                "hit_rate_at_3": r.hit_rate_at_3, "hit_rate_at_5": r.hit_rate_at_5,
                "mrr": r.mrr, "recall_at_3": r.recall_at_3,
                "recall_at_5": r.recall_at_5, "created_at": str(r.created_at),
            }
            for r in runs
        ],
        "total": total,
    })
```

#### 5.2.4 修改 `app/main.py` — 条件注册

```python
# app/main.py
from app.config import settings

# ... 其他路由注册 ...

if settings.RAG_EVAL_ENABLED:
    from app.api.v1.eval import router as eval_router
    app.include_router(eval_router, prefix="/api/v1")
# RAG_EVAL_ENABLED=False 时路由不注册，/eval/* 返回 404
```

---

### 5.3 P2: 完整 ReAct 多工具

#### 5.3.1 新增 `app/agent/graph_react.py`

采用**裸 OpenAI client** 方案，不使用 LangGraph 的 `ToolNode` 或 `bind_tools`。

```python
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
    "2. 基于检索结果回答，引用来源编号\n"
    "3. 如果检索结果不足以回答，请明确说明\n"
    "4. 用中文回答，保持专业友好\n"
    "5. 不需要反复检索同一问题，获取足够信息后直接回答"
)


def create_react_graph(llm_client, tools: list, model_name: str, max_iterations: int = 5):
    """创建 ReAct 循环 Agent Graph

    流程: call_model → [tool_call?] → call_tool → call_model → ... → end

    参数:
        llm_client: AsyncOpenAI 客户端
        tools: LangChain @tool 装饰的异步工具列表
        model_name: LLM 模型名
        max_iterations: 最大工具调用次数（来自 settings.AGENT_MAX_TOOL_ITERATIONS，Phase 3 已定义）
    """
    tool_map = {t.name: t for t in tools}

    async def call_model(state: AgentState) -> dict:
        """LLM 节点：决定调用工具或直接回答

        使用裸 OpenAI client 的 tools 参数传递 function calling 定义。
        """
        messages = list(state.get("messages", []))

        # 确保 system prompt 存在
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
            }
        else:
            return {
                "messages": [{"role": "assistant", "content": msg.content or ""}],
                "sources": state.get("sources", []),
                "tool_calls_log": state.get("tool_calls_log", []),
            }

    async def call_tool(state: AgentState) -> dict:
        """工具执行节点：执行所有 pending tool_calls

        返回的 tool message 使用 dict 格式：
        {"role": "tool", "content": "...", "tool_call_id": "..."}
        LangGraph 的 add_messages reducer 可正确处理此格式。
        """
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else {}

        tool_calls = []
        if isinstance(last_msg, dict):
            tool_calls = last_msg.get("tool_calls", [])

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
        """路由：检查最后一条消息是否包含 tool_calls"""
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else {}
        tool_calls = (
            last_msg.get("tool_calls", [])
            if isinstance(last_msg, dict)
            else []
        )
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
```

> **修正说明（v4）**：`type(first_msg).__name__ != "SystemMessage"` 改为 `not isinstance(first_msg, SystemMessage)`——`isinstance` 正确处理继承关系，且更符合 Python 惯例。assistant message 保留 `"content": msg.content or ""`，不省略 content 字段。

#### 5.3.2 修改 `app/services/agent_service.py` — `_get_graph()`

```python
def _get_graph(self, checkpointer=None):
    """Phase 5: 根据 REACT_ENABLED 选择 graph 实现"""
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
        from app.agent.graph import create_agent_graph
        graph = create_agent_graph(
            llm_client=self.llm_client,
            tools=tools,
            model_name=self.llm_model,
            max_iterations=settings.AGENT_MAX_TOOL_ITERATIONS,
        )

    return graph.compile(checkpointer=checkpointer)
```

#### 5.3.3 修改 `app/config.py`

```python
# ── Phase 5: ReAct ──
REACT_ENABLED: bool = False  # True=完整 ReAct 循环；False=简化两阶段（fallback）
```

> `AGENT_MAX_TOOL_ITERATIONS` 在 Phase 3 已定义（默认 `5`），Phase 5 复用，无需新增。

---

### 5.4 P2: 模型 Provider 抽象

#### 5.4.1 修改 `app/core/llm_client.py`

```python
"""
共享 LLM 客户端工厂

Phase 5 P2: 支持多 provider（ollama / deepseek / qwen / openai）。
返回 (client, model_name) 元组，调用方无需感知 provider 差异。
"""
from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


def _get_model_name(purpose: str) -> str:
    """根据 provider + purpose 返回正确的模型名"""
    provider = settings.LLM_PROVIDER

    if provider == "ollama":
        if purpose == "agent":
            return settings.AGENT_MODEL
        elif purpose == "embed":
            return settings.EMBEDDING_MODEL
        else:
            return settings.LLM_MODEL_NAME
    else:
        if purpose == "agent":
            return settings.CLOUD_AGENT_MODEL
        else:
            return settings.CLOUD_MODEL_NAME


@lru_cache(maxsize=4)
def get_llm_client(purpose: str = "default") -> tuple[AsyncOpenAI, str]:
    """获取 (AsyncOpenAI 客户端, 模型名) 元组

    lru_cache 基于 purpose 参数做缓存（缓存键为 purpose 字符串），
    与返回值类型无关。maxsize=4 覆盖四种组合。
    """
    provider = settings.LLM_PROVIDER

    if provider == "ollama":
        base_url = settings.LLM_BASE_URL
        api_key = settings.LLM_API_KEY
    elif provider == "deepseek":
        base_url = settings.CLOUD_BASE_URL or "https://api.deepseek.com/v1"
        api_key = settings.CLOUD_API_KEY
    elif provider == "qwen":
        base_url = settings.CLOUD_BASE_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        api_key = settings.CLOUD_API_KEY
    elif provider == "openai":
        base_url = settings.CLOUD_BASE_URL or "https://api.openai.com/v1"
        api_key = settings.CLOUD_API_KEY
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")

    if purpose == "agent":
        timeout = settings.AGENT_TIMEOUT_SECONDS
    elif purpose == "embed":
        timeout = settings.EMBEDDING_TIMEOUT_SECONDS  # Phase 5: 使用配置值替代硬编码 60.0
    else:
        timeout = settings.LLM_TIMEOUT_SECONDS

    client = AsyncOpenAI(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=timeout,
        max_retries=settings.LLM_MAX_RETRIES,
    )
    model_name = _get_model_name(purpose)
    return client, model_name
```

#### 5.4.2 修改调用方（共 5 处）

| 文件 | 变更 |
|------|------|
| `app/services/agent_service.py` | `self.llm_client = get_llm_client("agent")` → `self.llm_client, self.llm_model = get_llm_client("agent")` |
| `app/services/rag_service.py` | `self.llm_client = get_llm_client("default")` → `self.llm_client, self.llm_model = get_llm_client("default")` |
| `app/services/eval_service.py` | `self.llm_client = get_llm_client("default")` → `self.llm_client, self.llm_model = get_llm_client("default")` |
| `app/services/query_rewrite_service.py` | 同上 |
| `app/services/embedding_service.py` | `get_llm_client(purpose="embed")` → 解构适配（模型名仍从 `settings.EMBEDDING_MODEL` 取） |

---

## 6. 前端变更

### 6.1 P0: Token 流式 — 前端改动

**前端几乎零改动**。`AgentStreamRenderer.handleEvent()` 的 default 分支已实现追加模式。

方案 A 后端仍以 `data:` 行逐 token 推送，前端无需区分"节点级"和"token 级"。若出现高频 SSE 推送导致渲染卡顿，可在 `AgentStreamRenderer` 中增加 50ms throttle。

### 6.2 P1: RAG 评测仪表盘

#### 6.2.1 新增 `frontend/src/views/eval/EvalDashboard.vue`

- 路由：`/kbs/:kbId/eval`
- 布局：数字卡片 + 历史评测记录表格
- 不依赖 ECharts

#### 6.2.2 新增 `frontend/src/api/eval.ts`

```typescript
import { request } from './request'

export function synthesizeQueries(kbId: number, count = 50) {
  return request.post('/eval/queries/synthesize', null, { params: { kb_id: kbId, count } })
}

export function runEval(kbId: number, topK = 5) {
  return request.post('/eval/run', null, { params: { kb_id: kbId, top_k: topK } })
}

export function listEvalRuns(kbId: number, page = 1, pageSize = 20) {
  return request.get('/eval/runs', { params: { kb_id: kbId, page, page_size: pageSize } })
}
```

#### 6.2.3 修改 `frontend/src/router/index.ts`

```typescript
{
  path: '/kbs/:kbId/eval',
  name: 'EvalDashboard',
  component: () => import('@/views/eval/EvalDashboard.vue'),
  meta: { title: 'RAG 评测' },
}
```

### 6.3 P2: ReAct 前端改动

**无需前端改动**。

---

## 7. 数据库变更

### 7.1 Alembic 迁移 — `phase5_001_eval_tables.py`

```python
"""Phase 5: RAG 评测表

Revision ID: phase5_001
Revises: phase4_001
"""
from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "sys_eval_query",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("sys_knowledge_base.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("relevant_chunk_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("relevant_doc_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("source", sa.String(20), nullable=False, server_default="synthetic"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_query_kb", "sys_eval_query", ["kb_id"])

    op.create_table(
        "sys_eval_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("sys_knowledge_base.id"), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True, comment="评测配置快照"),
        sa.Column("hit_rate_at_3", sa.Float(), nullable=True),
        sa.Column("hit_rate_at_5", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("recall_at_3", sa.Float(), nullable=True),
        sa.Column("recall_at_5", sa.Float(), nullable=True),
        sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_run_kb", "sys_eval_run", ["kb_id"])
    op.create_index("idx_eval_run_kb_time", "sys_eval_run", ["kb_id", "created_at"])

    op.create_table(
        "sys_eval_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("sys_eval_run.id"), nullable=False),
        sa.Column("query_id", sa.Integer(), sa.ForeignKey("sys_eval_query.id"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, comment="第一个相关文档的排名，0=未命中"),
        sa.Column("hits_in_top_k", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieved_chunk_ids", sa.Text(), nullable=False, comment="JSON array"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_eval_result_run", "sys_eval_result", ["run_id"])


def downgrade():
    op.drop_table("sys_eval_result")
    op.drop_table("sys_eval_run")
    op.drop_table("sys_eval_query")
```

### 7.2 Phase 5 不涉及现有表变更

---

## 8. 验证步骤

### C0: interrupt_after 前置验证（P0 编码前必做）

在正式编码前，编写独立测试脚本验证 `interrupt_after` + `aupdate_state` + 下轮 `ainvoke` 的完整行为。

```python
"""C0: interrupt_after + aupdate_state + 下轮 ainvoke 行为验证

运行前准备：
  - 需提前准备 kb_id=1 的测试知识库（含已上传文档），确保 retrieve_knowledge
    能返回非空结果。若测试环境无可用 KB，可替换为 mock retrieve 工具：
      @tool
      async def retrieve_knowledge(question: str, top_k: int = 5) -> list[dict]:
          return [{"chunk_id": 1, "document_id": 1, "content": "mock", "score": 0.9}]

验证目标：
1. ainvoke 后 interrupt_after=["call_tool"] 正确暂停
2. aupdate_state 后 checkpoint 记录完整（含 assistant message + sources + tool_calls_log）
3. aupdate_state 后同一 thread_id 再次 ainvoke 不会触发 call_model 重复执行
   （关键断言：roles 中 assistant 数量 = 1，即只有 aupdate_state 写入的那一条）
4. 3 轮对话后服务重启，第 3 轮能正确恢复上下文

通过标准：
- 所有断言通过
- sys_agent_checkpoint 表中可观察到 call_tool 阶段的 checkpoint
  和 aupdate_state 写入的 checkpoint
- 步骤 4 重启后仍能正确恢复（跨 restart checkpoint 一致性）

测试通过后再进入 §5.1.3 chat_stream() 的正式编码。
"""
import asyncio
import json

# 测试配置
THREAD_ID = "conv:test_c0"
CHECKPOINT_NS = ""

async def test_interrupt_after_consistency():
    from app.agent.graph import create_agent_graph, AgentState
    from app.agent.tools.retrieve_knowledge import create_retrieve_knowledge_tool
    from app.agent.checkpointer import MySQLCheckpointSaver
    from app.core.database import async_session_factory
    from app.core.llm_client import get_llm_client

    llm_client, model_name = get_llm_client("agent")

    # 准备 checkpointer
    async with async_session_factory() as db:
        # 创建测试工具（需 kb_id=1 的测试 KB，或替换为上方 docstring 中的 mock 工具）
        retrieve_tool = create_retrieve_knowledge_tool(db, kb_id=1, user_id=1)
        tools = [retrieve_tool]

        graph = create_agent_graph(llm_client=llm_client, tools=tools, model_name=model_name)
        checkpointer = MySQLCheckpointSaver(async_session_factory)
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_after=["call_tool"],
        )

        config = {"configurable": {"thread_id": THREAD_ID}}
        initial_state: AgentState = {
            "messages": [
                {"role": "system", "content": "测试系统提示"},
                {"role": "user", "content": "测试问题"},
            ],
            "kb_id": 1,
            "user_id": 1,
            "sources": [],
            "tool_calls_log": [],
        }

        # Step 1: ainvoke → 应在 call_tool 后暂停
        state = await compiled.ainvoke(initial_state, config)
        assert state is not None, "ainvoke 应返回 state"
        msgs = state.get("messages", [])
        assert len(msgs) > 0, "state 应包含 messages"
        # 验证 call_tool 阶段状态已保留
        assert len(state.get("sources", [])) >= 1, "sources 应保留 call_tool 输出"
        assert len(state.get("tool_calls_log", [])) >= 1, "tool_calls_log 应保留 call_tool 输出"
        print("[C0] Step 1 通过: interrupt_after 正确暂停，sources/tool_calls_log 已保留")

        # Step 2: aupdate_state 写入 assistant message
        saved_sources = list(state.get("sources", []))
        saved_log = list(state.get("tool_calls_log", []))
        await compiled.aupdate_state(
            config,
            {"messages": [{"role": "assistant", "content": "LLM 生成的回答"}],
             "sources": saved_sources,
             "tool_calls_log": saved_log},
        )
        print("[C0] Step 2 通过: aupdate_state 写入成功")

        # Step 3: 同一 thread_id 再次 ainvoke
        state2 = await compiled.ainvoke(
            {"messages": [{"role": "user", "content": "第二轮问题"}],
             "kb_id": 1, "user_id": 1, "sources": [], "tool_calls_log": []},
            config,
        )
        msgs2 = state2.get("messages", [])
        roles = [m.get("role") if isinstance(m, dict) else str(m) for m in msgs2]
        print(f"[C0] Step 3 roles: {roles}")

        # ★ 关键断言：call_model 未被重复执行 ★
        # 若 roles = ['system','user','tool','assistant','user','tool','assistant']
        # 则 assistant 出现 2 次 = call_model 被重复触发（预期外的行为）
        assistant_count = roles.count("assistant")
        tool_count = roles.count("tool")
        assert assistant_count == 1, (
            f"预期 assistant 数量=1（仅 aupdate_state 写入），实际={assistant_count}。"
            f"若 >1 则 call_model 被重复执行，interrupt_after 方案需重新评估。"
        )
        assert tool_count >= 1, f"应保留 call_tool 的 tool message，实际 tool_count={tool_count}"
        # 验证 sources 和 tool_calls_log 跨轮保留
        assert len(state2.get("sources", [])) >= 1, "sources 应跨轮保留"
        assert len(state2.get("tool_calls_log", [])) >= 1, "tool_calls_log 应跨轮保留"
        print("[C0] Step 3 通过: 下轮 ainvoke 正常，call_model 未重复执行，"
              "sources/tool_calls_log 跨轮保留")

        # Step 4: 手动验证 checkpoint 表
        async with async_session_factory() as check_db:
            from sqlalchemy import text
            result = await check_db.execute(
                text("SELECT COUNT(*), type FROM sys_agent_checkpoint "
                     "WHERE thread_id=:tid GROUP BY type"),
                {"tid": THREAD_ID},
            )
            rows = result.all()
            print(f"[C0] Step 4 checkpoint: {rows}")

    print("[C0] 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(test_interrupt_after_consistency())
```

> **若 C0 不通过**：说明 LangGraph 1.2.9 的 `interrupt_after` + MySQL Checkpointer 存在兼容性问题。此时应：
> 1. 检查 C0 失败的 assert 位置（Step 1/2/3）
> 2. 若 Step 3 失败（`assistant_count > 1`）→ call_model 被重复执行，考虑改用 `interrupt_before=["call_model"]` + `ainvoke(None, config)` resume；或改用 Option B（双 graph 方案）
> 3. 若均不可行 → 降级决策：将 P0 延后到 Phase 6，Phase 5 仅执行 P1 + P2

---

### C1: Token 级流式 — 打字机效果 + checkpoint 一致性

```bash
# 1. 确认默认配置
python -c "from app.config import settings; print(settings.STREAMING_TOKEN_LEVEL, settings.REACT_ENABLED)"
# → True, False

# 2. SSE 流式对话（验证首 token 延迟）
curl -s -N "http://localhost:8000/api/v1/agent/chat-stream?kb_id=17&question=介绍一下知识库中的内容" \
  -H "Authorization: Bearer $AT"
# → 检索完成后 data: 行逐 token 推送，首 token 应在检索完成 1s 内到达

# 3. 单轮 checkpoint 验证
mysql> SELECT COUNT(*), type FROM sys_agent_checkpoint
      WHERE thread_id='conv:X' GROUP BY type;
# → 应有 type='checkpoint' 记录

# 4. ★ 3 轮对话 + 服务重启（本轮使用 chat-stream，验证 token 流式 checkpoint 跨 restart 恢复）★
# Step a: 第 1 轮 — GET /agent/chat-stream
curl -s -N "http://localhost:8000/api/v1/agent/chat-stream?kb_id=17&question=第一轮问题：什么是知识库？" \
  -H "Authorization: Bearer $AT"
# → 观察逐 token 输出，记录最终 done 事件中的 conversation_id

# Step b: 第 2 轮 — POST /agent/chat（非流式，验证混合模式）
curl -s -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"kb_id": 17, "question": "第二轮问题：它有哪些核心功能？", "conversation_id": X}'
# → 应正常恢复上下文

# Step c: 重启服务
# Step d: 第 3 轮 — GET /agent/chat-stream（token 流式，验证跨重启恢复）
curl -s -N "http://localhost:8000/api/v1/agent/chat-stream?kb_id=17&question=第三轮：复述我第一个问题&conversation_id=X" \
  -H "Authorization: Bearer $AT"
# → ★ 应能复述"什么是知识库？"——验证 token 流式产生的 checkpoint 跨 restart 恢复

# 5. 降级测试
STREAMING_TOKEN_LEVEL=false
# → 回退到节点级输出（Phase 4 行为）

# 6. REACT_ENABLED 覆盖测试
REACT_ENABLED=true
# → 走 graph_react 路径 + 节点级输出，STREAMING_TOKEN_LEVEL 被忽略
```

✅ 通过标准：
- C0 前置验证通过（interrupt_after 行为符合预期）
- `STREAMING_TOKEN_LEVEL=True, REACT_ENABLED=False` 时首 token 延迟 < 2s
- 3 轮（含 2 轮 chat-stream + 服务重启）checkpoint 恢复正常
- `STREAMING_TOKEN_LEVEL=False` 回退到 Phase 4
- `REACT_ENABLED=True` 时 STREAMING_TOKEN_LEVEL 被忽略

### C2: RAG 评测 — 自动合成 + 执行 + 权限

```bash
# 1. 合成查询集
curl -s -X POST "http://localhost:8000/api/v1/eval/queries/synthesize?kb_id=17&count=20" \
  -H "Authorization: Bearer $AT"
# → {"code": 0, "data": {"generated": 20}}

# 2. 无权限用户 → 403
curl -s -X POST "http://localhost:8000/api/v1/eval/queries/synthesize?kb_id=17&count=20" \
  -H "Authorization: Bearer $OTHER_USER_TOKEN"
# → {"code": 403, "message": "无权访问该知识库"}

# 3. 执行评测
curl -s -X POST "http://localhost:8000/api/v1/eval/run?kb_id=17&top_k=5" \
  -H "Authorization: Bearer $AT"
# → {"code": 0, "data": {"hit_rate@3": 0.xxx, ...}}

# 4. 指标合理性：hit_rate@5 ≥ hit_rate@3；MRR ∈ [0,1]；recall@5 ≥ recall@3

# 5. RAG_EVAL_ENABLED=false → /eval/* 返回 404
```

✅ 通过标准：
- 三个端点均校验 KB 访问权限
- `RAG_EVAL_ENABLED=False` 时路由不注册

### C3: ReAct 多工具循环

```bash
REACT_ENABLED=true
curl -s -X POST "http://localhost:8000/api/v1/agent/chat" ... # tool_calls 可能含多个工具

REACT_ENABLED=false  # → Phase 4 行为

REACT_ENABLED=true STREAMING_TOKEN_LEVEL=true
# → STREAMING_TOKEN_LEVEL 被忽略，走节点级输出
```

✅ 通过标准：ReAct 模式下 LLM 自主决定工具调用；`REACT_ENABLED=True` 时 STREAMING_TOKEN_LEVEL 自动失效。

### C4: 模型 Provider 切换

```bash
LLM_PROVIDER=ollama  # → 正常对话

python -c "
from app.core.llm_client import get_llm_client
client, model = get_llm_client('agent')
print(model)  # → qwen2.5:7b
"

# 云端 API Key 为空 → 启动报错
LLM_PROVIDER=deepseek
CLOUD_API_KEY=""
python -c "from app.config import settings"
# → ValueError: LLM_PROVIDER=deepseek 但 CLOUD_API_KEY 为空
```

✅ 通过标准：provider 切换后模型名正确；云端 API Key 为空时启动报错。

### C5: 向后兼容验证（全量回归）

| # | 测试项 | Phase | 验证 |
|:--:|--------|:-----:|:----:|
| P1 | `POST /qa/search` | P1 | ✅ 200 |
| P2 | `POST /qa/ask` | P2 | ✅ 200 |
| P3 | `GET /qa/ask-stream` | P2 | ✅ SSE 正常 |
| P4 | 文档上传 + SSE 进度 | P2/3 | ✅ 200 |
| P5 | `POST /agent/chat` | P3 | ✅ 200，Checkpointer 持久化正常 |
| P6 | `GET /agent/chat-stream` | P3 | ✅ SSE 正常（三种路径均可降级） |
| P7 | 对话 CRUD | P3 | ✅ 创建/删除/列表/消息加载 |
| P8 | KBMember 缓存 | P4 | ✅ 正缓存 + 否定缓存 + invalidate |
| P9 | `alembic downgrade -1` | P5 | ✅ `sys_eval_*` 表删除成功 |
| P10 | `alembic upgrade head` | P5 | ✅ phase5_001 重建成功 |

### C6: 前端构建验证

```bash
cd frontend && npm run build  # → Vite build 通过
```

---

## 9. 风险与缓解

| # | 风险 | 影响 | 概率 | 缓解 |
|:--:|------|:----:|:----:|------|
| R1 | qwen2.5:7b function calling 不稳定，ReAct 模式工具调用错误率高 | 🔴 高 | 中 | `REACT_ENABLED` 默认 `False`；在 14b 上验证后切换；云端备选 |
| R2 | `interrupt_after` + MySQL Checkpointer 存在兼容性问题（LangGraph 1.2.9 bug） | 🔴 高 | 低 | **C0 前置验证**（编码前执行）；不通过则延后 P0 到 Phase 6 或改用 interrupt_before |
| R3 | 逐 token SSE 高频推送导致前端渲染卡顿 | 🟡 中 | 低 | 50ms throttle；Phase 4 已验证追加模式可用 |
| R4 | LLM 自动合成的评测查询集质量低 | 🟡 中 | 中 | 人工抽检；支持按 query_id 删除 + 重新合成 |
| R5 | 云端 API 切换后成本失控 | 🟡 中 | 低 | 开发默认 Ollama；CLOUD_API_KEY 为空且 LLM_PROVIDER!=ollama 时启动报错 |
| R6 | ReAct 改造影响 Phase 4 能力 | 🟡 中 | 低 | `REACT_ENABLED=False` 完全走 Phase 4 逻辑；C5 全量回归 |
| R7 | `get_llm_client` 返回值变更导致调用方遗漏适配 | 🟢 低 | 低 | 5 个文件改动模式一致，编码阶段一次性完成 |
| R8 | `chat()` 非流式误用 interrupt 路径导致 checkpoint 不一致 | 🟢 低 | 低 | `chat()` 方法独立实现，永远不传 `interrupt_after` |

---

## 10. 文件创建/修改顺序

### 后端

```
 1. app/config.py                              — 修改: 新增 STREAMING_TOKEN_LEVEL / RAG_EVAL_ENABLED / REACT_ENABLED
                                                  + EMBEDDING_TIMEOUT_SECONDS
                                                  + CLOUD_MODEL_NAME / CLOUD_AGENT_MODEL / CLOUD_BASE_URL / CLOUD_API_KEY
                                                  + _validate_security 增加云端 API Key 校验
 2. app/core/llm_client.py                     — 修改: 新增 _get_model_name()；
                                                  get_llm_client() 返回 tuple[AsyncOpenAI, str]；
                                                  embed 超时使用 settings.EMBEDDING_TIMEOUT_SECONDS (P2)
 3. app/services/agent_service.py              — 修改: 适配 get_llm_client 新签名 (self.llm_client, self.llm_model)
 4. app/services/rag_service.py                — 修改: 适配 get_llm_client 新签名
 5. app/services/query_rewrite_service.py      — 修改: 适配 get_llm_client 新签名
 6. app/services/embedding_service.py          — 修改: 适配 get_llm_client 新签名
 7. app/agent/nodes.py                         — 新增: 抽取 call_tool 节点公共逻辑 (P0)
 8. app/agent/graph.py                         — 修改: 引用 nodes.create_call_tool_node()；
                                                  create_agent_graph 签名增加 max_iterations (P0)
 9. app/models/eval.py                         — 新增: EvalQuery + EvalRun + EvalResult (P1)
10. app/models/__init__.py                     — 修改: 注册 EvalQuery / EvalRun / EvalResult
11. alembic 迁移                                — phase5_001_eval_tables (P1)
12. app/services/eval_service.py               — 新增: 评测服务（适配 get_llm_client 新签名）(P1)
13. app/api/v1/eval.py                         — 新增: 评测路由（含 _require_kb_access）(P1)
14. app/main.py                                 — 修改: 条件注册 eval 路由（RAG_EVAL_ENABLED）(P1)
15. app/agent/graph_react.py                   — 新增: ReAct 循环 Graph（裸 OpenAI client；
                                                  isinstance 修正）(P2)
16. app/agent/tools/get_kb_info.py              — 修改: 确认工具可注册 (P2)
17. app/services/agent_service.py              — 修改: chat_stream() 集成方案 A token 流式（interrupt_after）(P0)
                                                  + 路径选择逻辑；chat() 永远不传 interrupt_after
```

### 前端

```
18. frontend/src/api/eval.ts                   — 新增: 评测 API 封装 (P1)
19. frontend/src/views/eval/EvalDashboard.vue  — 新增: 评测仪表盘页面 (P1)
20. frontend/src/router/index.ts               — 修改: 新增 /kbs/:kbId/eval 路由 (P1)
```

### 无变更文件（保持 Phase 4 状态）

```
app/agent/checkpointer.py               — 不变
app/agent/tools/retrieve_knowledge.py   — 不变
app/models/checkpoint.py                — 不变
app/services/kb_member_cache.py         — 不变
app/services/kb_service.py              — 不变
app/services/conversation_service.py    — 不变
app/services/hybrid_search_service.py   — 不变
app/services/checkpoint_cleanup_service.py — 不变
app/api/v1/agent_chat.py                — 不变
app/api/v1/qa.py                        — 不变
frontend/src/composables/useSSE.ts      — 不变
frontend/src/composables/useMarkdown.ts — 不变
frontend/src/components/AgentStreamRenderer.vue — 不变
frontend/src/components/ChatMessage.vue — 不变
```

---

## 附录 A: 端点汇总

| 方法 | 路径 | Phase | 权限 | 说明 |
|:----:|------|:-----:|:----:|------|
| POST | `/agent/chat` | P3 | KB 成员 | 非流式（永远不受 STREAMING_TOKEN_LEVEL 影响） |
| GET | `/agent/chat-stream` | P3 | KB 成员 | SSE 流式（P5 支持三种路径切换） |
| POST | `/eval/queries/synthesize` | P5 | KB 成员 | 自动合成评测查询集 |
| POST | `/eval/run` | P5 | KB 成员 | 执行评测 |
| GET | `/eval/runs` | P5 | KB 成员 | 查询评测历史 |
| POST | `/qa/search` | P1 | KB 成员 | 纯检索（不变） |
| POST | `/qa/ask` | P2 | KB 成员 | RAG 问答（不变） |
| GET | `/qa/ask-stream` | P2 | KB 成员 | RAG 流式问答（不变） |

## 附录 B: .env 新增配置项一览

```bash
# ── Phase 5: Token 流式 ──
STREAMING_TOKEN_LEVEL=true     # True=方案 A 逐 token SSE；False=节点级降级
                               # 注意：REACT_ENABLED=true 时本开关自动失效

# ── Phase 5: RAG 评测 ──
RAG_EVAL_ENABLED=true          # True=注册 /eval 路由；False=不注册，请求返回 404

# ── Phase 5: ReAct ──
REACT_ENABLED=false            # True=完整 ReAct 循环；False=简化两阶段

# ── Phase 5: 模型 Provider ──
LLM_PROVIDER=ollama            # ollama | deepseek | qwen | openai
CLOUD_MODEL_NAME=deepseek-chat
CLOUD_AGENT_MODEL=deepseek-chat
CLOUD_BASE_URL=                # 云端 API 地址
CLOUD_API_KEY=                 # 云端 API Key（LLM_PROVIDER != ollama 时必填）

# ── Phase 5: Embedding 超时 ──
EMBEDDING_TIMEOUT_SECONDS=60.0 # embedding 请求超时（秒）
```

## 附录 C: 工具注册约定

```python
# app/agent/tools/<tool_name>.py
from langchain_core.tools import tool

def create_<tool_name>(db, kb_id: int, user_id: int):
    @tool
    async def <tool_name>(...) -> dict | list[dict] | str:
        """工具描述 — LLM 据此决定何时调用"""
        ...
    return <tool_name>
```

在 `AgentService._build_tools()` 中注册：

```python
def _build_tools(self):
    tools = [create_retrieve_knowledge_tool(self.db, self.kb_id, self.user_id)]
    if settings.REACT_ENABLED:
        tools.append(create_kb_info_tool(self.db, self.kb_id, self.user_id))
    return tools
```
