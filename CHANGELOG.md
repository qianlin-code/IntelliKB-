# Changelog

## [1.0.1] - 2026-07-31

### Hotfix — 上线前问题修复

- **SSE 认证修复**: 浏览器 EventSource 无法携带自定义请求头，SSE 端点现在优先读取 URL 查询参数 `access_token` 进行认证，避免 Cookie 中过期 token 导致 401。
  - 影响文件: `app/depends/auth.py`, `frontend/src/composables/useSSE.ts`
- **RAG 流式消息持久化**: 修复流式输出完成后用户问题/ assistant 回答消失的问题。`_persist_qa_messages` 改为后台任务 + 独立数据库会话，避免客户端断开导致事务回滚。
  - 影响文件: `app/services/rag_service.py`, `frontend/src/api/qa.ts`, `frontend/src/views/qa/QAPage.vue`
- **检索相似度阈值**: 新增 `SEARCH_SCORE_THRESHOLD=0.55` 配置，过滤低质量向量检索结果；前端“仅检索”模式增加相关度标签与空状态提示。
  - 影响文件: `app/config.py`, `app/services/vector_store.py`, `frontend/src/views/qa/QAPage.vue`
- **Embedding 服务强制本地 Ollama**: 切换 `LLM_PROVIDER=deepseek` 后，Embedding 仍使用 `OLLAMA_BASE_URL` 与 `EMBEDDING_MODEL`，避免调用云端模型导致 500。
  - 影响文件: `app/core/llm_client.py`
- **Agent 流式路径健壮性**: 修复 Python 3.11 嵌套 f-string JSON 序列化语法错误；`done` 事件 payload 提前构造。
  - 影响文件: `app/services/agent_service.py`
- **文档同步**: 更新 `docs/tech-debt.md`, `docs/project-status.md`, `docs/roadmap.md`, `README.md`, `.gitignore`。

---

## [1.0.0] - 2026-07-30

### v1.0.0 正式发布 — 首个生产就绪版本

经过 11 个阶段的迭代开发，IntelliKB 从零构建为完整的 AI 智能知识库平台。

---

### Phase 0: 项目初始化 (2026-06)
- 基础目录结构、Docker 环境、FastAPI 应用框架
- Pydantic Settings 配置管理、.env 注入
- MySQL 8.0 + Redis 7 + Chroma 基础设施

### Phase 1: 核心知识库 (2026-06)
- **认证**: JWT Bearer Token + API Key 双认证、bcrypt 密码哈希、注册/登录/登出/刷新
- **知识库 CRUD**: 创建/查看/更新/删除、owner 权限校验
- **文档管理**: PDF/DOCX/MD/TXT 上传、魔数校验、pdfplumber 解析、RecursiveCharacterTextSplitter 分块
- **向量化**: Chroma 向量存储、bge-small-zh embedding

### Phase 2: 混合检索与流式问答 (2026-06)
- **混合检索**: BM25 关键词 + 向量语义、RRF 融合
- **Cross-encoder Rerank**: ms-marco-MiniLM-L-6-v2 精排
- **查询改写**: LLM-based 多轮指代消解
- **SSE 流式 QA**: 检索结果 → LLM 逐 token 输出
- **异步文档解析**: BackgroundTasks + Redis Pub/Sub 进度推送
- **知识库成员**: owner/editor/viewer 三级角色

### Phase 3: Agent 对话 (2026-06)
- **LangGraph Agent**: 两阶段 call_tool → call_model 流程
- **对话管理**: Conversation + Message 两张表持久化
- **MySQL Checkpointer**: 对话中断恢复、多轮上下文
- **SSE Pub/Sub**: Redis 频道发布文档解析进度

### Phase 4: 质量增强 (2026-07)
- **前端 Markdown 渲染**: marked + highlight.js + DOMPurify
- **语义标题**: LLM 自动生成对话标题（≤12 字）
- **历史截断**: 滑动窗口 20 轮 / 8192 tokens
- **ReAct 完整循环**: call_model ↔ call_tool 条件边
- **对话 CRUD API**: 列表/创建/详情/删除/消息列表

### Phase 5: 体验增强 (2026-07)
- **Token 级流式 SSE**: interrupt_after 方案 A、打字机效果
- **RAG 评测框架**: EvalRun/EvalQuery/EvalResult、Hit Rate/MRR/Recall
- **ReAct 热切换**: REACT_ENABLED 配置开关、graph.py ↔ graph_react.py
- **模型 Provider**: Ollama / DeepSeek / 通义千问 / OpenAI 统一接口
- **EvalDashboard**: 评测操作/指标卡片/模型对比/历史记录

### Phase 6: 云端 Agent 激活 (2026-07)
- **DeepSeek 云端 LLM**: 显式确认 CLOUD_LLM_CONFIRMED
- **成本追踪**: Redis 日/月 token 计数、DAILY/MONTHLY_TOKEN_LIMIT
- **云端 Fallback**: DeepSeek 故障 → 本地 Ollama 自动降级
- **OLLAMA_BASE_URL 独立配置**: 修复 fallback 使用错误 URL 的关键 bug
- **LangGraph checkpoint 修复**: pending_writes 2-tuple vs 3-tuple 兼容

### Phase 7: 生产就绪加固 (2026-07)
- **Reranker 离线化**: RERANK_LOCAL_DIR 本地模型缓存、下载后自动缓存
- **健康检查**: /api/v1/health + /api/v1/ready、Ollama 15s 缓存
- **Token 精确计数**: response.usage 提取真实值（4 条路径全覆盖）
- **Path 3 _record_cost 补填**: 修复节点级流式路径遗漏
- **集成测试**: tests/integration/ 3 个模块 11 项测试
- **前端代码分割**: QAPage 1,002KB→11KB (-99%)、vendor 拆分

### Phase 8: RAG 质量飞跃 (2026-07)
- **中文 Reranker**: bge-reranker-base 优先 → ms-marco-MiniLM 降级 → disable
- **查询重写 A/B/C**: 指代消解 / 问题拆解 / 关键词提取
- **答案引用溯源**: [source:N] 标记、citation_parser 解析、前端弹窗显示原文
- **多轮对话优化**: 19 个指代词检测、上下文摘要注入（≤120 字）
- **语义分块**: Markdown 标题→空行→句子 四级优先级
- **Badcase 面板**: EvalDashboard 未命中查询详情
- **推荐问题**: 3 个 follow_up_questions + "换一批"按钮

### Phase 9: 用户体验与对话智能 (2026-07)
- **会话导出**: Markdown（含来源引用）、后端驱动
- **对话搜索**: 标题+消息内容搜索、日期范围、KB 筛选
- **Agent 人设**: 每 KB 自定义 system_prompt
- **来源面板**: SourcePanel 双向高亮交互、移动端抽屉
- **消息编辑重生成**: 截断+checkpoint 清理+重调 Agent
- **会话置顶/收藏**: is_pinned/is_starred
- **暗黑模式**: useDarkMode composable
- **对话分叉**: 基于历史消息创建分支

### Phase 10: 企业级管理 (2026-07)
- **RBAC**: superadmin/admin/user 系统角色 + require_* 守卫
- **审计日志**: 16 种操作类型、异步写入、6 维筛选查询
- **资源配额**: KB/文档/成员/存储 4 种配额、API 端点集成
- **API Key 增强**: 名称/启用/月配额管理
- **管理后台**: AdminLayout + 4 页面（用户/日志/配置/统计）
- **系统配置热更新**: SystemConfig 模型 + 内存缓存
- **用户个人中心**: GET /auth/me/usage

### Phase 11: 项目收尾 (2026-07)
- **README 重写**: 功能矩阵、快速开始、环境变量、架构图
- **架构图**: 3 张 Mermaid 图（部署/分层/流程）
- **部署指南**: docs/deployment.md 6 章节
- **初始化脚本**: init.sh + init.ps1
- **Docker 优化**: 数据卷持久化、非 root 用户
- **技术债务**: 12 项分类清单
- **路线图**: Phase 12-16 建议方向
- **开源材料**: MIT LICENSE + CONTRIBUTING.md + CI workflow
- **全量回归**: 87 文件语法通过

### v1.0.0 发布冻结 (2026-07-30)
- CHANGELOG.md 本文件
- RELEASE_NOTES.md 发布说明
- docs/project-status.md 项目状态报告
- 版本号统一: APP_VERSION 0.1.0 → 1.0.0
- 文档一致性检查
- Git tag v1.0.0
