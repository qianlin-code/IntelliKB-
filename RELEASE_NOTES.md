# IntelliKB v1.0.1 Release Notes

> 🧠 基于 RAG + Agent 的企业级智能知识库平台 — 首个生产就绪版本

**发布日期**: 2026-07-31
**版本号**: v1.0.1
**代号**: First Flight 🚀

---

## v1.0.1 Hotfix 摘要（2026-07-31）

本次在 v1.0.0 基础上修复了上线前验证阶段发现的关键问题：

1. **SSE 认证**：浏览器 EventSource 无法携带自定义 Header，SSE 端点现在优先读取 URL 查询参数 `access_token`，避免 Cookie 中过期 token 导致 401。
2. **RAG 消息持久化**：流式输出完成后用户问题/回答消失的问题已修复， persistence 改为后台任务 + 独立数据库会话。
3. **检索阈值**：新增 `SEARCH_SCORE_THRESHOLD=0.55`，低相似度结果被过滤；前端“仅检索”增加相关度标签与空状态提示。
4. **Embedding 强制本地 Ollama**：即使 `LLM_PROVIDER=deepseek`，Embedding 仍走 `OLLAMA_BASE_URL`，避免 500。
5. **Agent 流式语法修复**：Python 3.11 嵌套 f-string JSON 序列化错误已修复。

详见 [CHANGELOG.md](https://github.com/qianlin-code/IntelliKB/blob/main/CHANGELOG.md)。

---

## 一句话简介

IntelliKB 是一个基于 RAG（检索增强生成）和 Agent 智能体的企业级知识库平台，支持本地 Ollama 推理和云端 DeepSeek 增强，提供从文档上传、智能检索到对话问答的完整闭环。

---

## 核心功能亮点

1. **混合检索 + Reranker 精排**: BM25 + 向量 + Cross-encoder 三级检索管线，中文 bge-reranker-base 优化
2. **Agent 智能对话**: LangGraph ReAct 循环、工具调用、MySQL Checkpointer 持久化、云端 Fallback 降级
3. **实时流式输出**: Token 级 SSE 打字机效果、[source:N] 引用溯源
4. **多轮上下文**: 指代词检测、上下文摘要注入、最多 20 轮历史对话
5. **评测驱动优化**: Hit Rate/MRR/Recall 自动评测、A/B 策略对比、Badcase 分析
6. **企业级管理**: RBAC 双层权限、16 种审计日志、资源配额控制
7. **多 Provider 切换**: Ollama / DeepSeek / 通义千问 / OpenAI 统一接口
8. **容器化部署**: Docker Compose 一键启动、离线部署方案、数据卷持久化
9. **前端 SPA**: Vue 3 + TypeScript + Element Plus、代码分割优化、管理后台
10. **50+ API 端点**: 按模块组织（auth/kb/document/qa/agent/conversation/eval/admin/health）

---

## 快速开始

```bash
git clone https://github.com/qianlin-code/IntelliKB.git && cd IntelliKB
cp .env.example .env
# 编辑 .env 设置 SECRET_KEY 和密码
docker compose up -d
# 运行初始化脚本
bash scripts/init.sh
# 访问 http://localhost:5173
```

---

## 系统要求

### 硬件

| 组件 | 最低                     | 推荐                |
| ---- | ------------------------ | ------------------- |
| CPU  | 4 核                     | 8 核                |
| RAM  | 8 GB                     | 16 GB               |
| VRAM | 6 GB (Ollama qwen2.5:7b) | 16 GB               |
| 磁盘 | 20 GB                    | 50 GB+ (含模型缓存) |

### 软件

| 组件           | 版本             |
| -------------- | ---------------- |
| Docker         | 24.0+            |
| Docker Compose | v2               |
| Python         | 3.11+ (本地开发) |
| Node.js        | 18+ (前端开发)   |
| MySQL          | 8.0              |
| Redis          | 7.x              |
| Ollama         | 最新版           |

---

## 已知限制

1. **ReAct 完整模式**需要 `REACT_ENABLED=true`，qwen2.5:7b 本地模式下 function calling 不稳定，推荐使用 DeepSeek 云端模式
2. **Ollama 模型下载**首次启动需联网下载 qwen2.5:7b (~4.7GB) 和 embedding 模型，耗时取决于网速
3. **Reranker bge-reranker-base** 模型约 1.3GB，首次加载需 5-30 秒（取决于硬件），之后加载本地缓存
4. **PDF 扫描件**默认 OCR_ENABLED=false，扫描版 PDF 无法提取文字（需安装 PaddleOCR）
5. **vendor-element (1.1MB)** 和 **vendor-markdown (983KB)** 为 Element Plus 和 highlight.js 完整库体积，CDN 加载可进一步优化
6. **单机 Chroma** 为本地文件存储，不支持分布式部署
7. **API Key 验证**在大规模用户（>1000）下性能有待优化（已知技术债 ADR-001）

---

## 从之前版本升级

IntelliKB v1.0.0 是首个正式版本，无历史版本需兼容。

### 升级数据库

```bash
# 自动: docker compose up -d (启动时自动执行 alembic upgrade head)
# 手动:
docker compose exec app alembic upgrade head
```

### 配置变更

- `.env` 中新增 `QUOTA_ENABLED` 和 `QUOTA_*` 系列配置（Phase 10）
- `.env` 中新增 `RERANK_MODEL_ZH` 和 `RERANK_MODEL_FALLBACK`（Phase 8）
- `docker-compose.yml` 新增 `uploads_data`、`reranker_models`、`chroma_data` 卷

---

## 贡献者

IntelliKB 由开发团队构建，从 Phase 0 到 Phase 11 共 12 个迭代阶段。

---

## 许可证

MIT License — 详见 [LICENSE](https://github.com/qianlin-code/IntelliKB/blob/main/LICENSE)。

---

## 相关链接

| 资源     | 地址                                                                              |
| -------- | --------------------------------------------------------------------------------- |
| README   | https://github.com/qianlin-code/IntelliKB/blob/main/README.md                     |
| 架构概览 | https://github.com/qianlin-code/IntelliKB/blob/main/docs/architecture-overview.md |
| 部署指南 | https://github.com/qianlin-code/IntelliKB/blob/main/docs/deployment.md            |
| 技术债务 | https://github.com/qianlin-code/IntelliKB/blob/main/docs/tech-debt.md             |
| 路线图   | https://github.com/qianlin-code/IntelliKB/blob/main/docs/roadmap.md               |
| API 文档 | http://localhost:8000/docs                                                        |
| 变更日志 | https://github.com/qianlin-code/IntelliKB/blob/main/CHANGELOG.md                  |
