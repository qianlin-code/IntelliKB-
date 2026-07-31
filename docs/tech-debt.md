# IntelliKB 技术债务清单

> 更新日期: 2026-07-31 | 版本: Phase 11

## 严重度说明

| 级别 | 含义 | 处理时间 |
|:----:|------|:--------:|
| 🔴 L1 | 影响安全/数据完整性，需立即处理 | 1-2 周 |
| 🟡 L2 | 影响性能/可维护性，按迭代计划处理 | 1-3 月 |
| 🟢 L3 | 不影响功能，长期改进 | 择机处理 |

---

## 当前债务

### 🔴 L1 — 高优先级

| # | 问题 | 文件/模块 | 影响 | 建议 |
|:--:|------|-----------|------|------|
| 1 | API Key 验证通过 prefix 缩小范围后 bcrypt 逐一比对，用户量 > 1000 时延迟 > 100ms | `app/depends/auth.py:_verify_api_key_and_get_user` | 高并发场景下 API Key 验证成为瓶颈 | 方案 A: 使用 `prefix.id.secret` 三段式存储 id hash → O(1) 查找。方案 B: 添加 `api_key_hash` 唯一索引 |
| 2 | JWT secret key 无轮换机制 | `app/core/security.py` | 密钥泄露后可长期伪造 Token | 实现 key rotation：支持多个 valid secret，轮换时逐步废弃旧 key |

### 🟡 L2 — 中优先级

| # | 问题 | 文件/模块 | 影响 | 建议 |
|:--:|------|-----------|------|------|
| 3 | `_truncate_history()` 使用字符数 // 2 估算 token，中文场景可偏差 15-30% | `app/services/agent_service.py` | 截断不够精确，浪费 context window | 引入 tiktoken 或等效 tokenizer |
| 4 | `rag_service.py` 的 LLM 调用没有 cloud→Ollama fallback，云端 503 时直接降级为固定提示 | `app/services/rag_service.py:ask()` / `ask_stream()` | DeepSeek 等云端 provider 不可用时，RAG 问答直接失败/返回低质量提示 | 复用 `agent_service.py` 的 `_try_cloud_fallback()` 机制 |
| 5 | Agent 来源面板把 RRF 分数当成 cosine 相似度显示，导致百分比极低（如 2%） | `frontend/src/components/SourcePanel.vue` + `app/services/hybrid_search_service.py` | 用户误解检索质量 | 统一分数语义或对 RRF 分数做归一化/排名展示 |
| 6 | Chroma 使用本地文件存储，不支持分布式部署 | `app/services/vector_store.py` | 仅限单机部署 | 评估 Milvus/Qdrant 作为可替换 backend |
| 7 | ReAct 模式下 tool schemas 硬编码，不支持动态工具注册 | `app/agent/graph_react.py` | 新增 Agent 工具需改代码 | 实现工具注册表模式 |
| 8 | 会话导出仅支持 Markdown，PDF 为 stub | `app/api/v1/conversations.py:export` | PDF 导出不可用 | 集成 weasyprint 或 reportlab |
| 9 | `bm25_service` 基于内存字典，重启丢失索引 | `app/services/bm25_service.py` | 重启后 BM25 需重建 | 评估 SQLite FTS5 或 Redis Search |

### 🟢 L3 — 低优先级

| # | 问题 | 文件/模块 | 影响 | 建议 |
|:--:|------|-----------|------|------|
| 10 | OCR 默认关闭，需手动安装 paddleocr/pytesseract | `app/services/doc_service.py` | 扫描件 PDF 无文本 | 在 Dockerfile 中预装 PaddleOCR |
| 11 | 多语言 Embedding 自动检测未实现 | `app/config.py:EMBEDDING_AUTO_DETECT_LANG` | 需手动选择 Embedding 模型 | 集成 langdetect/fasttext 检测语言 |
| 12 | 前端 vendor-element (1.1MB) 和 vendor-markdown (983KB) 超过 500KB | `frontend/vite.config.ts` | 首屏加载较慢 | element-plus 按需引入 + CDN 加载 |
| 13 | EvalDashboard 评测对比仅支持 2 个 provider | `frontend/src/views/eval/EvalDashboard.vue` | 无法同时对比多个模型 | 扩展为 N×N 矩阵 |
| 14 | 审计日志无自动清理/归档机制 | `app/models/audit_log.py` | 表无限增长 | 添加 TTL 清理任务（保留 90 天） |

---

## 已修复债务

| # | 问题 | 修复阶段 | 修复方式 |
|:--:|------|:--------:|----------|
| — | Fallback 客户端使用了错误的 LLM_BASE_URL | Phase 6 fix | 新增 OLLAMA_BASE_URL 独立配置 |
| — | LangGraph pending_writes 2-tuple vs 3-tuple 不兼容 | Phase 6 fix #7 | `_cleanup_orphan_checkpoint()` |
| — | Path 3 流式路径 `_record_cost()` 缺失 | Phase 7 P0.3 | 补填调用 |
| — | Reranker 断网时 huggingface 超时阻塞 | Phase 7 P0.1 | 本地模型缓存 + 降级链 |
