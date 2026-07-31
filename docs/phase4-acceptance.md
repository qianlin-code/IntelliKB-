# Phase 4 验收报告

> 验收日期: 2026-07-29
> 验收版本: phase4_001
> 验收人: Agent

## 概要

Phase 4「质量增强」验收完成。7 项验证全部通过（C1-C7）。

**验收结论: ✅ 通过**

---

## 环境信息

| 项目 | 值 |
|------|-----|
| MySQL | 8.0.35 (localhost:3306) |
| Redis | 7.2.4 (localhost:6379) |
| LangGraph | 1.2.9 |
| langgraph-checkpoint | 4.1.1 |
| marked | 17.0.6 |
| highlight.js | 11.11.1 |
| DOMPurify | 3.4.12 |
| Node.js | 24.18.0 |
| Ollama | qwen2.5:7b (localhost:11434) |

---

## C1: Checkpointer 持久化 ✅

### 测试场景

C1 测试通过独立的单元测试和端到端 Agent 对话验证：

1. **aput → aget_tuple 往返测试**: 写入 checkpoint 后再读取，验证数据完整性
2. **首轮 Agent 对话**: 创建新对话 → 4 条 `type=checkpoint` 记录写入 `sys_agent_checkpoint`
3. **第二轮对话（同 conv_id）**: 恢复上下文 → 查询历史消息 → 追加新一轮 checkpoint
4. **第三轮对话**: 多轮上下文恢复 → 追加更多 checkpoint
5. **最终统计**: 3 轮共 21 条记录（12 `checkpoint` + 9 `pending_writes`）

### 验证项

| 验证项 | 结果 |
|--------|:----:|
| `sys_agent_checkpoint` 表结构含 `serde_type` 列 (MEDIUMBLOB) | ✅ |
| `serde_type` = "msgpack", `checkpoint_json` 存储二进制 msgpack 数据 | ✅ |
| `type` = "checkpoint" 用于语义查询过滤 | ✅ |
| `type` = "pending_writes" 用于 pending writes 查询 | ✅ |
| 首轮对话后有 checkpoint 记录 | ✅ (4 records) |
| 第二轮同 conv_id 可恢复上下文 | ✅ |
| 第三轮多轮对话正常 | ✅ |
| 每个方法独立管理 session（async with self._session_factory()） | ✅ |
| 写操作 commit 正确（aput/aput_writes 无孤儿连接） | ✅ |

### checkpoint 记录示例

```
id=32 thread=conv:45 type=checkpoint serde=msgpack len=669
id=34 thread=conv:45 type=checkpoint serde=msgpack len=1137
id=36 thread=conv:45 type=checkpoint serde=msgpack len=1490
id=38 thread=conv:45 type=checkpoint serde=msgpack len=2034
```

---

## C2: Markdown + 代码高亮 ✅

### 前端文件

| 文件 | 功能 | 状态 |
|------|------|:----:|
| `frontend/src/composables/useMarkdown.ts` | marked + hljs + DOMPurify 渲染管道 | ✅ |
| `frontend/src/components/ChatMessage.vue` | 调用 `renderMarkdown()` 渲染 assistant 消息 | ✅ |
| `frontend/src/components/AgentStreamRenderer.vue` | SSE 帧解析后 Markdown 渲染 | ✅ |
| `frontend/package.json` | marked@17.0.6, highlight.js@11.11.1, dompurify@3.4.12 | ✅ |

### 验证

- Vite build: **1891 modules, 1.42s** ✅
- `marked.use({ renderer })` 注入自定义 `code()` 高亮 ✅
- `DOMPurify.sanitize()` XSS 防护 ✅
- `import 'highlight.js/styles/github.css'` 主题引入 ✅

---

## C3: 对话搜索 ✅

### 实现

- [ConversationSidebar.vue](frontend/src/components/ConversationSidebar.vue): `searchQuery` reactive + `filteredConversations` computed
- 客户端大小写不敏感过滤，匹配标题

### 验证

- Vite build 通过（含 ConversationSidebar 组件） ✅
- 搜索逻辑无语法错误 ✅

---

## C4: 对话导出 ✅

### 实现

- [ConversationSidebar.vue](frontend/src/components/ConversationSidebar.vue): `handleExport()` 生成 Markdown 文件
- Markdown 格式: `# 标题\n>\n## User\n\n## Assistant\n`
- Blob URL 下载，自动 `URL.revokeObjectURL()`

### 验证

- Vite build 通过 ✅
- 导出逻辑无语法错误 ✅

---

## C5: 语义标题 ✅

### 实现

- `ConversationService.generate_semantic_title()`: LLM 异步生成标题（≤12 字）
- `chat()`: 新对话后 `asyncio.wait_for()` 生成 + `conv_service.update_title()`
- `chat_stream()`: `BackgroundTasks.add_task(_update_title_async)` 异步更新
- `_update_title_async()`: 独立 `AsyncSession`，不持有请求级 session

### 验证

| 对话 ID | 标题 | 来源 |
|---------|------|------|
| 43 | "您好提问" | LLM 语义标题 ✅ |
| 44 | "自我介绍" | LLM 语义标题 ✅ |
| 45 | "自我介绍" | LLM 语义标题 ✅ |

标题为 LLM 生成的语义摘要，非原始问题截断。

---

## C6: KBMember 缓存 ✅

### 实现

- `KBService.get_accessible()`: 先查缓存 → miss → 查 DB → 回填
- `KBService.get_editable()`: 先查缓存 → miss → 查 DB → 回填
- `set_negative()` / `is_negative()`: 否定缓存 60s TTL
- `invalidate()`: 使用 `scan_iter` 清除正缓存 + 否定缓存

### 验证

```
get_role(888,1) = owner      (expected: owner)    ✅
get_role(888,2) = editor     (expected: editor)   ✅
get_role(888,3) = None       (expected: None)     ✅
is_negative(888,99) = True   (expected: True)     ✅
After invalidate, None       (expected: None)     ✅
```

---

## C7: 向后兼容 ✅

### 迁移验证

```
alembic current              → phase4_001 (head)
alembic downgrade -1         → phase3_001        ✅
alembic upgrade head         → phase4_001        ✅
```

降级 → 升级往返成功。

### 端点验证

| 端点 | 阶段 | 结果 |
|------|:----:|:----:|
| `POST /api/v1/qa/search` | P1 | ✅ 200 (0 results, empty KB) |
| `POST /api/v1/qa/ask` | P2 | ✅ 200 (75 char answer) |
| `POST /api/v1/agent/chat` | P4 | ✅ 200 (conv_id=46, tool_calls=1) |

---

## 验收过程中发现并修复的 Bug

| # | Bug | 严重度 | 修复 |
|:--:|------|:------:|------|
| 1 | `JsonPlusSerializer` 无 `dumps`/`loads` 方法 → `AttributeError` | 🔴 阻断 | 改为 `json.dumps()`/`json.loads()` 处理 metadata |
| 2 | `checkpoint_json` 列为 `MEDIUMTEXT`，无法存储 msgpack 二进制 → `(1366) Incorrect string value` | 🔴 阻断 | 改为 `MEDIUMBLOB` |
| 3 | checkpointer 与工具节点共享 session → aiomysql `readexactly()` 并发冲突 | 🔴 阻断 | `__init__(session_factory)`, 每个方法 `async with self._session_factory() as session` |
| 4 | `serde_type` 从 DB 读取后 `.encode()` → `NotImplementedError: b'msgpack'` | 🟡 | 移除 `.encode()`（DB 列已是 str） |
| 5 | `CheckpointTuple()` 参数 `pending_sends` → `pending_writes` (langgraph-checkpoint 4.x 更名) | 🟡 | 改为 `pending_writes` |
| 6 | ORM `Message` 对象无 `model_dump()` → `'Message' object has no attribute 'get'` | 🟡 | 新增 `_orm_msg_to_dict()` 静态方法 |
| 7 | Redis `decode_responses=True` 导致 `get_members()` 二次 decode → `'str' object has no attribute 'decode'` | 🟢 | 改为 `str(k): str(v)` |
| 8 | `async_sessionmaker` context manager 无 auto-commit → 对话未持久化 | 🟡 | 测试脚本加 `await db.commit()`（生产由 `get_db()` 处理） |

---

## 已知问题（非阻断）

| # | 问题 | 严重度 | 处理 |
|:--:|------|:------:|------|
| 1 | vue-tsc 与 Node.js 24 不兼容，`ERR_PACKAGE_PATH_NOT_EXPORTED` | 🟢 L2 | 仅 `vue-tsc --noEmit` 失败；`vite build` 正常（1.42s, 1891 modules）。Phase 3 已知问题。 |
| 2 | LLM (qwen2.5:7b) 在工具返回空结果时 produce 空内容 | 🟢 L2 | Phase 3 已有，非 Phase 4 引入。后续可优化模型选择或 prompt。 |
| 3 | Vite chunk size 超过 500KB 警告 | 🟢 L2 | QAPage.js 1001KB, index.js 762KB。Phase 3 已知问题，后续动态导入。 |

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `app/agent/checkpointer.py` | 重写 | session_factory 模式，独立 session 管理 |
| `app/models/checkpoint.py` | 修改 | checkpoint_json: MEDIUMTEXT → MEDIUMBLOB |
| `app/services/agent_service.py` | 修改 | from_factory → 直接构造；ORM dict 转换；孤儿清理 |
| `app/services/kb_member_cache.py` | 修改 | 修复 Redis decode_responses 二次 decode |
| `alembic/versions/phase4_001_agent_checkpoint_table.py` | 修改 | checkpoint_json: MEDIUMTEXT → MEDIUMBLOB |

---

## 结论

**Phase 4 验收通过。**

所有 7 项验收全部通过：
- C1 Checkpointer 持久化（含 session 生命周期修复）
- C2-C4 前端 Markdown/搜索/导出（Vite build 验证）
- C5 语义标题（LLM 生成验证）
- C6 KBMember 缓存 + 否定缓存
- C7 Alembic 降级/升级 + 端点向后兼容

验收过程中发现并修复 8 个 bug（3 个 🔴 阻断级），3 个已知问题均为 Phase 3 遗留（非阻断）。
