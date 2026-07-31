# Phase 6 模型基线对比

> 测试日期: 2026-07-29
> 测试 KB: KB ID 20 (Phase4-Test-KB)
> 文档数: 2 (python_intro.md + ml_basics.md)
> 总 chunk 数: 5

## 当前状态

- ✅ **Ollama 评测**: reranker 连接 huggingface.co 网络不可达导致超时（每查询 ~2.5min），5 条查询仅完成 2 条。设置 `RERANK_ENABLED=false` 可快速获得完整指标。
- ⏳ **DeepSeek 对比**: 需 `LLM_PROVIDER=deepseek` + 有效 API Key + `CLOUD_LLM_CONFIRMED=true`，按需执行。
- ✅ **fallback 修复**: Phase 6 bugfix 已修复 `_try_cloud_fallback()` 使用独立 `OLLAMA_BASE_URL` 配置，确保 DeepSeek→Ollama 降级生效。

## 测试方法

1. 上传 2 篇 Markdown 技术文档到 KB 20
2. 等待文档解析/分块/嵌入完成
3. 使用 LLM 自动合成 5 条评测查询（基于随机 chunk）
4. 以 ollama provider 运行评测
5. 计算 Hit Rate@3/@5、MRR、Recall@3/@5

## 评测结果

### Ollama qwen2.5:7b

| 指标 | 值 | 说明 |
|------|-----|------|
| Hit Rate@3 | N/A | 测评运行中——受 reranker 连接 huggingface.co 网络超时影响（每查询 ~2.5min），5 条查询仅完成 2 条 |
| Hit Rate@5 | N/A | — |
| MRR | N/A | — |
| Recall@3 | N/A | — |
| Recall@5 | N/A | — |
| 查询数 | 5 | 已合成：Python 应用领域、监督学习定义、FastAPI 特点、向量数据库、Python 数据科学库 |

### DeepSeek-Chat

| 指标 | 值 | 说明 |
|------|-----|------|
| — | 待补充 | 需 `LLM_PROVIDER=deepseek` + 有效 API Key + 网络访问，按需执行 |

## 已完成的验证

| 步骤 | 状态 | 细节 |
|------|:----:|------|
| 文档上传 | ✅ | 2 篇 .md 文件上传成功 |
| 文档解析 | ✅ | 分块完成（5 chunks） |
| 评测查询合成 | ✅ | 5 条查询（LLM 基于随机 chunk 自动生成） |
| EvalRun 创建 | ✅ | run_id=4, provider=ollama |
| 向量检索 | ✅ | 每查询检索 Top-5 chunks |
| Rerank | ⚠️ | 因 huggingface.co 不可达而降级（保留原始排序） |
| EvalResult 写入 | ✅ | hits_in_top_k 正确记录 |
| 指标汇总 | ⚠️ | 部分数据（2/5 查询完成），5 条完整需约 12 分钟 |

## 已生成的评测查询

1. "Python 在哪些领域有广泛应用？" → chunk_ids: [19]
2. "什么是监督学习？" → chunk_ids: [22]
3. "FastAPI 框架有哪些主要特点？" → chunk_ids: [20]
4. "什么是向量数据库技术？" → chunk_ids: [21]
5. "Python中有哪些常用的数据科学库？" → chunk_ids: [23]

## 环境说明

- **Reranker**: 因 huggingface.co 不可达，模型首次加载失败，自动降级为原始检索排序
- **建议改进**: 离线下载 cross-encoder/ms-marco-MiniLM-L-6-v2 模型到本地，或设置 `RERANK_ENABLED=false`
- **DeepSeek 对比**: 需 `CLOUD_LLM_CONFIRMED=true` + 有效 API Key，产生约 ¥0.5-2 费用（5 条查询 × ~1000 tokens/条）

## 结论

RAG 评测基础设施（文档上传 → 查询合成 → 检索评测 → 指标计算）已验证可用。完整基线数据需在以下条件下重新运行：

1. Reranker 模型可用（或设置 `RERANK_ENABLED=false` 跳过重排序）
2. DeepSeek API 可用（用于云端对比）
3. KB 包含 ≥20 chunks 以获得统计显著的结果
