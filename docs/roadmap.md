# IntelliKB 路线图

> 更新日期: 2026-07-31

## 已完成阶段

| Phase | 名称 | 核心交付 | 状态 |
|:-----:|------|----------|:----:|
| 0 | 基础架构 | FastAPI + MySQL + Redis + Docker + JWT 认证 | ✅ |
| 1 | 知识库核心 | KB CRUD + 成员权限 + 文档上传/解析/分块/向量化 | ✅ |
| 2 | 混合检索 | BM25 + 向量检索 + RRF 融合 + Reranker + 查询改写 + 异步解析 | ✅ |
| 3 | Agent 对话 | LangGraph Agent + Conversation + MySQL Checkpointer + SSE 进度 | ✅ |
| 4 | 质量增强 | 对话持久化 + 语义标题 + 消息管理 + 完整 ReAct Graph | ✅ |
| 5 | 体验增强 | Token 流式 SSE + 评测框架 + ReAct 热切换 + 模型 Provider | ✅ |
| 6 | 云端激活 | DeepSeek 云端 LLM + Fallback 降级 + 成本追踪 | ✅ |
| 7 | 生产加固 | Reranker 离线化 + 健康检查 + Token 精确计数 + 集成测试 + 前端优化 | ✅ |
| 8 | RAG 质量 | 中文 Reranker + 查询重写 A/B/C + 引用溯源 + 多轮优化 + 语义分块 | ✅ |
| 9 | 用户体验 | 会话导出/搜索 + Agent 人设 + 来源面板 + 编辑重生成 + 置顶/收藏 | ✅ |
| 10 | 企业管理 | RBAC + 审计日志 + 配额控制 + API Key 管理 + 管理后台 | ✅ |
| 11 | 项目收尾 | README 重写 + 架构图 + 部署文档 + 回归测试 + 开源准备 | ✅ |

---

## 建议的未来方向

### Phase 12: 多模态支持
**优先级**: 🟡 中 | **工作量**: 3-4 周

- 图片上传与理解（CLIP/ViT embedding）
- 多模态 RAG（图文混合检索）
- 表格数据解析与问答

### Phase 13: 知识图谱集成
**优先级**: 🟢 低 | **工作量**: 4-6 周

- 实体识别与关系抽取
- Neo4j 图谱存储
- GraphRAG 混合检索

### Phase 14: 多租户架构
**优先级**: 🟡 中 | **工作量**: 3-4 周

- 组织/工作空间隔离
- 跨组织数据隔离（Row-Level Security）
- SSO/LDAP 集成

### Phase 15: 插件系统
**优先级**: 🟢 低 | **工作量**: 4-6 周

- 自定义文档解析器
- 自定义 Agent 工具注册
- 第三方 LLM Provider 接入

### Phase 16: 协同编辑
**优先级**: 🟢 低 | **工作量**: 3-4 周

- WebSocket 实时协作
- 知识库协同编辑
- 评论与审阅流程

---

## 技术演进方向

| 方向 | 当前 | 建议升级 | 原因 |
|------|------|----------|------|
| 向量数据库 | Chroma (本地文件) | Milvus / Qdrant | 分布式 + 更高并发 |
| API Key | 单 Key per User | 多 Key + 细粒度权限 | 多场景隔离 |
| 前端 Bundle | vendor-element 1.1MB | Element Plus 按需引入 | 首屏加载优化 |
| 审计日志 | 无清理机制 | TTL 自动归档 | 存储增长控制 |
| 测试覆盖 | 集成测试覆盖核心路径 | 单元测试 + E2E | 重构信心 |
