# IntelliKB 部署指南

## 目录

1. [Docker Compose 部署](#docker-compose-部署)
2. [环境变量配置详解](#环境变量配置详解)
3. [首次初始化](#首次初始化)
4. [离线部署](#离线部署)
5. [升级指南](#升级指南)
6. [常见问题排查](#常见问题排查)

---

## Docker Compose 部署

### 前置条件

- Docker 24.0+
- Docker Compose v2
- 8 GB+ RAM（Ollama 需要 6GB+ VRAM）
- 20 GB+ 磁盘

### 步骤

```bash
# 1. 克隆项目
git clone https://github.com/yourname/intellikb.git
cd intellikb

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，确保以下变量已设置:
#   SECRET_KEY=<随机64字符密钥>
#   DB_PASSWORD=<强密码>
#   MYSQL_ROOT_PASSWORD=<强密码>
#   MYSQL_PASSWORD=<与 DB_PASSWORD 一致>
#   LLM_BASE_URL=http://host.docker.internal:11434/v1   (Docker 容器访问宿主机 Ollama)
#   OLLAMA_BASE_URL=http://host.docker.internal:11434/v1

# 3. 准备 Ollama（docker-compose 未内置 Ollama 服务）
# 在宿主机安装 Ollama 并拉取模型:
#   ollama pull qwen2.5:7b
#   ollama pull nomic-embed-text
# 确保 Ollama 监听 0.0.0.0:11434，或 host.docker.internal 能解析到宿主机。

# 4. 启动项目自带服务（MySQL/Redis/App）
docker compose up -d

# 5. 查看服务状态
docker compose ps
# 所有服务应显示 "healthy"

# 6. 初始化
# Linux/macOS:
bash scripts/init.sh
# Windows PowerShell:
powershell -File scripts/init.ps1

# 7. 访问
# 前端:     http://localhost:5173
# API 文档:  http://localhost:8000/docs
# 管理后台:  http://localhost:5173/admin
```

### 服务端口

| 服务 | 端口 | 用途 | 备注 |
|------|:----:|------|------|
| FastAPI App | 8000 | 后端 API | docker-compose 内置 |
| Vue Dev Server | 5173 | 前端开发 | 需单独 `npm run dev` |
| MySQL | 3306 | 数据库 | docker-compose 内置 |
| Redis | 6379 | 缓存/消息 | docker-compose 内置 |
| Ollama | 11434 | LLM 推理 | **宿主机独立运行**，未在 docker-compose 中定义 |

### 数据卷

| 卷 | 类型 | 容器路径 | 内容 |
|---|------|----------|------|
| `mysql_data` | Docker 命名卷 | `/var/lib/mysql` | 数据库文件 |
| `redis_data` | Docker 命名卷 | `/data` | Redis 持久化 |
| `uploads_data` | Docker 命名卷 | `/app/uploads` | 上传文件 |
| `reranker_models` | Docker 命名卷 | `/app/reranker_models` | Reranker 模型缓存 |
| `chroma_data` | Docker 命名卷 | `/app/chroma_data` | Chroma 向量持久化 |

---

## 环境变量配置详解

### 必需配置

```bash
# 生成随机密钥: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=<至少 32 字符的随机字符串>
DB_PASSWORD=<强密码>
MYSQL_ROOT_PASSWORD=<强密码>
MYSQL_PASSWORD=<与 DB_PASSWORD 相同>
```

### LLM 配置

```bash
# 本地 Ollama (默认)
LLM_PROVIDER=ollama
# Docker 容器访问宿主机 Ollama 必须使用 host.docker.internal
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL_NAME=qwen2.5:7b

# Fallback 专用地址（与 LLM_PROVIDER 无关，云端故障时自动降级用）
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
OLLAMA_API_KEY=ollama

# 云端 DeepSeek
# LLM_PROVIDER=deepseek
# CLOUD_BASE_URL=https://api.deepseek.com/v1
# CLOUD_API_KEY=sk-your-deepseek-key
# CLOUD_LLM_CONFIRMED=true
```

### 性能调优

```bash
# 数据库连接池
DB_POOL_SIZE=20          # 增加可提高并发
DB_MAX_OVERFLOW=30

# RAG 缓存
RAG_CACHE_ENABLED=true
RAG_CACHE_TTL_SECONDS=3600

# Agent 超时
AGENT_TIMEOUT_SECONDS=180
AGENT_MAX_TOOL_ITERATIONS=5
```

---

## 首次初始化

### 自动初始化

```bash
# scripts/init.sh 自动完成:
# 1. 等待所有服务健康检查通过
# 2. 运行 alembic upgrade head (数据库迁移)
# 3. 下载 Reranker 模型到本地 (可选)
# 4. 创建超级管理员账户
```

### 手动初始化

```bash
# 1. 数据库迁移
docker compose exec app alembic upgrade head

# 2. 下载 Reranker 模型 (可选，首次需要网络)
docker compose exec app python scripts/download_reranker.py
# 下载全部三层模型:
# docker compose exec app python scripts/download_reranker.py --all

# 3. 创建超级管理员
docker compose exec app python -c "
from app.core.database import async_session_factory
from app.services.auth_service import AuthService
import asyncio

async def create_superadmin():
    async with async_session_factory() as db:
        service = AuthService(db)
        user = await service.register('admin', 'YourPassword123', 'admin@example.com')
        user.system_role = 'superadmin'
        await db.commit()
        print(f'Superadmin created: {user.username}')

asyncio.run(create_superadmin())
"
```

---

## 离线部署

### 预下载模型

在有网络的机器上提前下载所需模型，然后复制到目标服务器。

```bash
# 1. 下载 Reranker 模型
python scripts/download_reranker.py --all
# 输出: reranker_models/BAAI_bge-reranker-base/
#       reranker_models/cross-encoder_ms-marco-MiniLM-L-6-v2/

# 2. 下载 Ollama 模型
ollama pull qwen2.5:7b
ollama pull bge-m3
ollama pull nomic-embed-text

# 3. 复制到目标服务器
# - reranker_models/ → 项目的 reranker_models/
# - Ollama 模型在 ~/.ollama/models/
```

### 离线启动

```bash
# 确保 .env 中:
RERANK_LOCAL_DIR=./reranker_models
LLM_BASE_URL=http://host.docker.internal:11434/v1   # Docker 内指向宿主机 Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1

docker compose up -d
```

---

## 升级指南

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 拉取最新 Docker 镜像
docker compose pull

# 3. 停止服务
docker compose down

# 4. 启动服务 (自动运行 alembic upgrade head)
docker compose up -d

# 5. 查看日志确认无错误
docker compose logs app --tail 50

# 6. 验证健康检查
curl http://localhost:8000/api/v1/health
```

### 数据备份

```bash
# 备份 MySQL
docker compose exec mysql mysqldump -u intellikb -p intellikb > backup_$(date +%Y%m%d).sql

# 备份上传文件
tar czf uploads_backup_$(date +%Y%m%d).tar.gz uploads/

# 备份 Reranker 模型
tar czf reranker_backup_$(date +%Y%m%d).tar.gz reranker_models/
```

---

## 常见问题排查

### 0. Docker 镜像加速器配置（中国大陆用户）

中国大陆网络环境下，Docker Hub (`registry.docker.io`) 可能连接超时，
导致 `docker compose up --build` 在拉取基础镜像时失败：

```
ERROR: failed to authorize: failed to fetch anonymous token:
  Get "https://auth.docker.io/token?...":
  dial tcp 69.171.228.74:443: connectex: A connection attempt failed...
```

**解决方案：配置 Docker 镜像加速器**

**Docker Desktop (Windows/Mac)**：

1. 打开 Docker Desktop → Settings → Docker Engine
2. 修改 `daemon.json`，添加 `registry-mirrors`：

```json
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://ccr.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ]
}
```

3. 点击 "Apply & Restart"

**Linux (daemon.json)**：

```bash
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://ccr.ccs.tencentyun.com",
    "https://docker.m.daocloud.io"
  ]
}
EOF
sudo systemctl restart docker
```

**验证**：
```bash
docker pull python:3.11-slim  # 应能正常拉取
```

**常见镜像源**：

| 镜像源 | 地址 |
|------|------|
| 中科大 | `https://docker.mirrors.ustc.edu.cn` |
| 腾讯云 | `https://ccr.ccs.tencentyun.com` |
| DaoCloud | `https://docker.m.daocloud.io` |
| 阿里云 | `https://<your-id>.mirror.aliyuncs.com`（需注册） |

### 1. 服务启动失败

```bash
# 查看日志
docker compose logs app --tail 100
docker compose logs mysql --tail 50

# 常见原因:
# - .env 未配置或配置错误
# - 端口冲突 (3306/6379/8000)
# - MySQL 未就绪 (等待 healthcheck 通过)
# - Docker 构建缓存冲突 → 使用 --no-cache 重新构建
# - Debian/PyPI 源不可达（国内网络）→ 见下方 1b
```

### 1b. Docker 构建网络问题（中国大陆用户）

**Dockerfile 已内置国内镜像 ARG 支持**，默认使用 USTC/清华镜像：

```bash
# 默认构建（使用国内镜像）
docker compose build --no-cache app

# 海外网络（跳过国内镜像）
docker compose build --no-cache --build-arg PIP_INDEX_URL="" --build-arg DEBIAN_MIRROR="" app

# 自定义镜像源
docker compose build --no-cache \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  --build-arg DEBIAN_MIRROR=mirrors.aliyun.com \
  app
```

**构建 ARG 参数**:

| ARG | 默认值 | 说明 |
|------|------|------|
| `PIP_INDEX_URL` | `https://pypi.tuna.tsinghua.edu.cn/simple` | pip 安装源 |
| `DEBIAN_MIRROR` | `mirrors.ustc.edu.cn` | apt 软件源 |

**Docker Hub 基础镜像**仍需通过「[镜像加速器](#0-docker-镜像加速器配置中国大陆用户)」配置。

### 1c. Docker 构建缓存 hash 冲突

```bash
# 现象: docker compose build 报 "Expected sha256 ... Got ..."
# 原因: Docker buildkit 缓存了旧层，与当前基础镜像不一致
# 解决: 清理缓存后重新构建
docker builder prune -f
docker compose build --no-cache app
```

> **关于 `requirements.txt` 跨平台兼容性**:
> 本项目使用纯版本约束（如 `fastapi>=0.115,<0.120`），不含 `--hash` 后缀。
> 这确保 Linux/macOS/Windows 上的 `pip install` 均可正常工作。
> 首次 `docker compose build` 时 `pip install` 从 PyPI 拉取包，PyPI 国内访问
> 通常不受影响；若遇 PyPI 超时，可在 Dockerfile 中配置 pip 镜像源。

### 2. Ollama 连接失败

```bash
# 确认 Ollama 正在运行
curl http://localhost:11434/api/tags

# Docker 内连接宿主机 Ollama（本项目 docker-compose 未内置 Ollama）
# 必须配置: LLM_BASE_URL=http://host.docker.internal:11434/v1
#           OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
#
# 如果 host.docker.internal 无法解析（如部分 Linux 发行版），可改为宿主机 IP：
#   LLM_BASE_URL=http://<宿主机IP>:11434/v1
#
# 仅在 Ollama 也跑在 Docker 网络中时才使用 http://ollama:11434/v1
```

### 2b. Ollama 并发性能限制

**本地 Ollama 部署不适合高并发场景**，这是模型单实例串行推理的固有瓶颈：

| 场景 | 并发数 | 典型响应时间 | 说明 |
|------|:------:|-------------|------|
| 单次问答 | 1 | 5-15s | 正常 |
| 轻量并发 | 2-3 | 15-30s | 可接受 |
| 中等并发 | 5-10 | 30-60s+ | 排队等待 GPU |
| 高并发 | 20+ | **超时/失败** | 严重瓶颈 |

**原因**: Ollama 以单进程加载一个模型实例，多个请求在 GPU 上排队串行执行。qwen2.5:7b (4.7GB) 在 6GB VRAM 上只能加载一个实例。

**生产环境建议**：
1. **轻量使用**（< 5 并发）：单实例 Ollama 可接受，建议设置 `AGENT_TIMEOUT_SECONDS=300`
2. **中等并发**（5-20 并发）：部署多个 Ollama 实例 + 负载均衡，或切换到云端 LLM
3. **高并发**（20+ 并发）：**必须使用云端 LLM**（DeepSeek / 通义千问 / OpenAI），设置 `LLM_PROVIDER=deepseek`

**切换到云端 LLM**（推荐用于生产环境）：
```bash
LLM_PROVIDER=deepseek
CLOUD_BASE_URL=https://api.deepseek.com/v1
CLOUD_API_KEY=sk-your-deepseek-key
CLOUD_LLM_CONFIRMED=true
```

**多实例 Ollama**（实验性，需要多 GPU）：
```bash
# 实例 1: CUDA_VISIBLE_DEVICES=0 OLLAMA_HOST=0.0.0.0:11434 ollama serve
# 实例 2: CUDA_VISIBLE_DEVICES=1 OLLAMA_HOST=0.0.0.0:11435 ollama serve
# 然后在应用层实现轮询负载均衡
```

**内置保护**：当云端 LLM 不可用时，系统会自动 Fallback 到本地 Ollama，但此时并发能力受限于上述限制。

### 3. Reranker 下载超时

```bash
# 方案 A: 设置代理
export HF_ENDPOINT=https://hf-mirror.com

# 方案 B: 离线部署
python scripts/download_reranker.py --all  # 在有网络的机器上执行
# 然后复制 reranker_models/ 目录到服务器

# 方案 C: 禁用 Reranker
# .env 中设置 RERANK_ENABLED=false
```

### 4. 数据库迁移失败

```bash
# 查看当前迁移版本
docker compose exec app alembic current

# 查看迁移历史
docker compose exec app alembic history

# 手动升级
docker compose exec app alembic upgrade head

# 回退一个版本
docker compose exec app alembic downgrade -1
```

### 5. API 返回 500

```bash
# 查看健康检查
curl http://localhost:8000/api/v1/health
# {"status":"ok","version":"0.1.0"}

# 查看就绪状态
curl http://localhost:8000/api/v1/ready
# {"status":"ready","details":{"db":true,"redis":true,"ollama":true}}

# 查看应用日志
docker compose logs app --tail 100 | grep ERROR
```

### 6. 前端构建失败

```bash
cd frontend
rm -rf node_modules
npm install
npx vite build
# 检查是否有 > 500KB chunk 警告
```
