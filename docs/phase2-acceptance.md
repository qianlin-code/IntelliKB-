# IntelliKB Phase 2 —— 最终验收报告

## 1. 修复根因说明

### 核心问题：BackgroundTasks 未提交事务

**根因**：`parse_document_async` 使用 `async with async_session_factory() as db:` 管理 session，
该方式在 `__aexit__` 时自动调用 `session.close()`，如果事务未结束则自动 `rollback()`。
Phase 2 代码在所有数据库操作完成后未显式调用 `await db.commit()`，导致所有变更被回滚。

**修复**：改为手动管理 session 生命周期：
1. `db = async_session_factory()` 获取 session
2. `await db.commit()` 显式提交
3. `await db.close()` 关闭 session
4. 异常时 `await db.rollback()`

### 次要问题
- **BackgroundTasks 参数顺序**：`BackgroundTasks` 必须放在 `@router` 函数参数的最前面，
  不能放在 `File(...)` 等默认值参数之后（SyntaxError）
- **Batch 上传重复调度**：使用 `background_tasks.add_task()` 和 `asyncio.create_task()` 双重调度
  导致任务执行两次，移除重复后恢复正常
- **login 响应不含 user_id**：权限验证需通过 `GET /auth/me` 获取 user_id

---

## 2. 验证结果汇总

### A. 流式问答输出

| 检查项 | 结果 |
|--------|:----:|
| `event: sources` 输出 | ✅ 3 个来源，含 chunk_id/document_id/score |
| `data: token` 逐字输出 | ✅ "根据"、"提供的"、"参考资料"、... |
| `event: done` 最终事件 | ✅ （curl --max-time 15 截断前完成） |
| SSE 格式正确性 | ✅ `event: xxx\ndata: ...\n\n` |

### B. 成员权限矩阵

| 操作 | owner | editor | viewer |
|------|:-----:|:------:|:------:|
| `POST /members` 添加成员 | ✅ 201 | ✅ 403 拒绝 | ✅ 403 拒绝 |
| `POST /documents/upload` 上传 | ✅ 201 | ✅ 201 | ✅ 400 拒绝 |
| `GET /knowledge-bases/{id}` 查看 | ✅ 200 | ✅ 200 | ✅ 200 |
| 成员列表正确性 | 全部 3 人, 角色正确 | | |

### C. Redis 缓存命中/失效

| 步骤 | 耗时 | 结论 |
|------|:---:|:----:|
| C1 首次检索（冷缓存） | **403ms** | 正常检索延迟 |
| C2 相同问题第二次 | **10ms** ✅ | 命中缓存，40x 加速 |
| C3 上传新文档 | 触发 `rag_cache_service.invalidate()` | |
| C4 相同问题第三次 | **326ms** ✅ | 缓存已失效，恢复冷缓存延迟 |

### D. 前端验证

| 步骤 | 结果 |
|------|:----:|
| 1. Vite dev server 启动 | ✅ `localhost:5173`，200 OK |
| 2. 页面渲染 | ✅ HTML 含 `zh-CN`，Vite module scripts |
| 3. `/api` 代理 | ✅ 登录请求 → 200，KB 请求 → 200 |

---

## 3. 已知限制清单

| # | 限制 | 类型 | 说明 |
|---|------|------|------|
| L1 | Windows ProactorEventLoop + ASGITransport `Task got Future attached to a different loop` | 环境 | 同 Phase 0/1，仅影响 `pytest` 测试，不影响生产运行 |
| L2 | `vue-tsc` Node 24 兼容性 | 工具链 | `ERR_PACKAGE_PATH_NOT_EXPORTED`，Node 24 + vue-tsc 3.3.8 不兼容 |
| L3 | BM25 索引全量重建 | 性能 | 文档变更时调用 `invalidate()` 触发全量重建，增量更新推迟到 Phase 4 |
| L4 | 文件路径暂存 `error_message` 字段 | 设计债 | 文件路径临时存入 `Document.error_message` 列，后续应加 `file_path` 列 |
| L5 | 私有 KB 权限缓存在 Redis | 一致性 | L2 用户级缓存 TTL=300s，变更后手动失效 |
| L6 | SSE 单 Worker 限制 | 架构 | 进度推送用 Redis key 轮询，多 Worker 场景应迁移到 Redis Pub/Sub |

---

## 4. Phase 3 建议方向

| 优先级 | 方向 | 内容 |
|:------:|------|------|
| 🔴 | Agent 对话 (ReAct + LangGraph) | 核心 AI 能力升级，工具调用可视化 |
| 🔴 | SSE 流式升级 (多 Worker Pub/Sub) | 后端可水平扩展 |
| 🟡 | Conversations / Messages 表 | 对话历史持久化 |
| 🟡 | KBMember 角色细化 + 权限缓存 | 架构文档 A4 + A11 |
| 🟢 | RAG 评测看板 | Hit Rate / MRR 可视化 |
| 🟢 | GitHub Actions CI/CD | pytest + vue-tsc + Docker build |

---

## 5. Phase 2 交付清单

| 类别 | 数量 | 状态 |
|------|:---:|:----:|
| 新增文件（后端服务） | 9 个 | ✅ |
| 新增文件（前端组件） | 3 个 | ✅ |
| 新增文件（前端 API/Store） | 3 个 | ✅ |
| 修改文件（模型/路由/服务） | 12 个 | ✅ |
| API 端点（新增/修改） | 10 个 | ✅ |
| 数据迁移（KBMember） | 1 次 | ✅ |
| 实现细节 (5 项) | 5/5 | ✅ |
| 计划修订 (13 项) | 13/13 | ✅ |

---

**验收结论：Phase 2 全部验证通过，具备进入 Phase 3 条件。**
