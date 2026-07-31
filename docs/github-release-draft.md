# GitHub Release Draft — IntelliKB v1.0.0

## 标题

**IntelliKB v1.0.0 — 首个生产就绪版本 🚀**

## 发布说明

基于 RAG + Agent 的企业级智能知识库平台，经过 12 个迭代阶段（Phase 0-11）开发，现已达到生产就绪状态。

支持本地 Ollama 推理和云端 DeepSeek 增强，提供从文档上传、智能检索到 Agent 对话的完整闭环。

## 安装

```bash
git clone https://github.com/yourname/intellikb.git
cd intellikb
cp .env.example .env
# 编辑 .env 设置 SECRET_KEY 和密码
docker compose up -d
bash scripts/init.sh
# 访问 http://localhost:5173
```

## 核心功能

- 🔍 混合检索 + Reranker 精排（BM25 + 向量 + bge-reranker-base）
- 🤖 Agent 智能对话（LangGraph ReAct、MySQL Checkpointer、云端 Fallback）
- 📊 评测驱动优化（Hit Rate/MRR/Recall、A/B 对比、Badcase 分析）
- 🏢 企业级管理（RBAC、审计日志、配额控制、管理后台）
- 🎨 现代化前端（Vue 3 + Element Plus、SSE 流式、Markdown 渲染）
- 🐳 一键部署（Docker Compose、离线方案、数据持久化）

## 资源

- 📖 [README](README.md)
- 🏗 [架构概览](docs/architecture-overview.md)
- 🚀 [部署指南](docs/deployment.md)
- 📝 [变更日志](CHANGELOG.md)
- 🔮 [路线图](docs/roadmap.md)

## 系统要求

- Docker 24.0+ / Docker Compose v2
- 8 GB+ RAM（Ollama qwen2.5:7b 需 6GB VRAM）
- 20 GB+ 磁盘
