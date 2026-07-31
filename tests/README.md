# IntelliKB 测试

## 运行说明

### 前置条件

- **MySQL** 可访问（通过 `.env` 配置 `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD`）
- **Redis** 运行（通过 `.env` 配置 `REDIS_HOST` / `REDIS_PORT`）
- **Ollama** 运行（Agent 集成测试需要，单元测试不需要）
- 已安装依赖：`pip install pytest pytest-asyncio httpx`

### 运行命令

```bash
# 全部单元测试（不需要 Ollama）
pytest tests/test_health.py tests/test_auth.py tests/test_kb.py tests/test_document.py -v

# 集成测试（需要后端在 8000 端口运行）
pytest tests/integration/ -v

# 按模块
pytest tests/test_auth.py -v
pytest tests/test_kb.py -v
pytest tests/test_document.py -v
pytest tests/integration/test_health.py -v
pytest tests/integration/test_qa.py -v
pytest tests/integration/test_agent_chat.py -v

# 全部测试（含集成测试）
pytest tests/ -v
```

### 数据库隔离

```bash
# 推荐：使用独立测试数据库
# 先在 MySQL 中创建: CREATE DATABASE intellikb_test;
SET DB_NAME=intellikb_test
pytest tests/ -v
```

### 测试环境配置建议

为获得稳定的集成测试结果，建议在 `.env` 中设置较高的频率限制：

```bash
# 测试环境：放宽频率限制，确保 test_user fixture 能创建独立用户
REGISTER_RATE_LIMIT_MAX=100     # 默认 10，测试时需要更高
LOGIN_RATE_LIMIT_MAX=100        # 默认 5
```

---

## 测试架构

### 单元测试 (`tests/`)

使用 ASGITransport 在进程中测试 FastAPI app。依赖真实 MySQL（Redis 可选）。

| 文件 | 内容 | 需要 Mock |
|------|------|-----------|
| `test_health.py` | 健康检查端点 | 无 |
| `test_auth.py` | 注册/登录/当前用户 | 无 |
| `test_kb.py` | KB CRUD | `mock_embedding_and_vector` |
| `test_document.py` | 文档上传/列表/删除 | `mock_embedding_and_vector` |
| `test_conversation_repo.py` | ConversationRepository CRUD | 无（直接测试 repo 层） |
| `test_fallback_e2e.py` | cloud → Ollama 降级 E2E | 无 |

### 集成测试 (`tests/integration/`)

使用真实 HTTP 客户端连接运行中的后端（`http://127.0.0.1:8000`）。

| 文件 | 内容 | 需要 |
|------|------|------|
| `test_health.py` | 健康检查 + 就绪探针 | 后端运行 |
| `test_qa.py` | RAG 搜索 + 问答 | 后端运行 + Ollama |
| `test_agent_chat.py` | Agent 对话 + 流式 | 后端运行 + Ollama |

### Fixture 策略

**单元测试** (`tests/conftest.py`)：

| Fixture | Scope | 说明 |
|---------|-------|------|
| `client` | session | ASGITransport 在进程中测试，所有模块共享 |
| `auth_header` | module | 注册新用户 → 登录 → 返回 token |
| `mock_embedding_and_vector` | function | monkeypatch 替换 EmbeddingService 和 VectorStoreService |
| `_clear_rate_limits` | session (autouse) | 清除 Redis 频率限制计数器 |

**集成测试** (`tests/integration/conftest.py`)：

| Fixture | Scope | 说明 |
|---------|-------|------|
| `client` | module | 真实 HTTP 客户端连 `http://127.0.0.1:8000` |
| `test_user` | module | 为每个测试模块创建独立用户（方案 A — 避免锁竞争） |
| `auth_header` | function | 使用 test_user 登录 |
| `test_kb_with_doc` | function | 自动创建测试 KB + 上传文档 + 等待索引 → 返回 kb_id → 测试后自动清理 |

---

## Windows 事件循环修复

### 问题

Python 3.13 的 Windows `ProactorEventLoop` + `aiomysql` + `ASGITransport` 组合存在
底层 IOCP 竞态问题：
- 数据库连接的 `_proactor` 在 I/O 操作中途变为 None → `AttributeError: 'NoneType' object has no attribute 'send'`
- 跨事件循环的 Future 泄露 → `Task got Future attached to a different loop`

### 修复方案

**1. SelectorEventLoop 策略** (`tests/conftest.py`):
```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
在导入 `app.main` 之前设置，避免 Proactor 的 IOCP 竞态。

**2. 统一事件循环作用域** (`pytest.ini`):
```ini
asyncio_default_fixture_loop_scope = session
asyncio_default_test_loop_scope = session
```
确保 fixture 和 test 运行在同一个 asyncio 事件循环中，
避免 fixture 创建的数据库连接在 test 的事件循环中出现 "different loop" 错误。

**3. Redis 限频清理** (`tests/conftest.py`):
`_clear_rate_limits` fixture (session-scoped, autouse=True) 在每次测试 session
开始时清除所有 `rate_limit:*` Redis key，避免历史限频计数导致 429 错误。

**4. 连接池清理** (`tests/conftest.py`):
`client` fixture teardown 中调用 `engine.dispose()` 释放数据库连接池。

### 影响范围

- 仅影响测试环境（`tests/conftest.py` + `pytest.ini`）
- 生产环境使用 `ProactorEventLoop`（默认），不受影响
- Linux/macOS 无事件循环问题，可直接 `pytest tests/ -v`

---

## 方案 A：配额锁竞争修复

**问题**：`kb_creation_lock`（MySQL `GET_LOCK`/`RELEASE_LOCK`）是用户级互斥锁。
当多个测试模块同时使用 `admin` 用户时，会争抢同一个锁（锁名 = `kb_quota_user_{user_id}`），
导致 10 秒超时后抛出 `BusinessError("系统繁忙，请稍后再试")`。

**修复**：`test_user` fixture（模块级）为每个测试模块创建独立的用户（`itest_xxxxxxxx`），
确保不同模块使用不同的 MySQL advisory lock，从根源消除锁竞争。

**重试策略**：当注册频率限制触发 429 时，fixture 使用指数退避重试（1s → 2s，最多 3 次）。
仅在所有重试失败后才回退到 `admin`。

**安全保证**：此修复仅修改测试 fixture（`tests/integration/conftest.py`），
不修改任何业务逻辑。`app/services/quota_service.py` 和 `app/api/v1/knowledge_bases.py`
的配额检查逻辑未受任何影响。

---

## 已知限制

### Windows 事件循环

**现象**：Windows 上测试 teardown 阶段可能触发：
```text
RuntimeError: Event loop is closed
RuntimeError: Task <Task ...> got Future attached to a different loop
```

**原因**：CPython Windows asyncio + pytest-asyncio + anyio 的已知边界问题。

**影响**：错误仅出现在 teardown 阶段（测试断言已执行完毕），不影响测试结果。
已通过 `try/except` 降级为 debug 日志。

**解决方案**：

| 方案 | 说明 |
|------|------|
| **SelectorEventLoop**（已配置） | `tests/conftest.py` 自动设置，消除 Proactor IOCP 竞态 |
| **WSL / Linux** | 在 WSL2 或 Linux 下运行测试（推荐），无此问题 |
| **GitHub Actions CI** | 使用 `ubuntu-latest` runner，无此问题 |
| **Docker 内运行** | `docker compose exec app pytest tests/ -v`，Linux 容器内无此问题 |

### Agent 测试需要 Ollama

Agent 集成测试（`test_agent_chat.py`）需要 Ollama 运行并已下载模型（如 `qwen2.5:7b`）。
无 Ollama 时跳过：

```bash
pytest tests/ -v --ignore=tests/integration/test_agent_chat.py
```

### 文档上传异步状态

文档上传后异步处理（uploading → parsing → chunking → indexing → done），
API 响应中的 `status` 字段可能在处理完成前返回。
`test_upload_md_document_201` 已改为接受所有非失败状态。

### 注册频率限制

`_clear_rate_limits` fixture 在 session 启动时自动清除 Redis 限频计数器。
若 Redis 不可用，频率限制静默跳过，不影响测试。

## CI 配置

推荐的 GitHub Actions workflow (`ci.yml`)：

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: rootpass123
          MYSQL_DATABASE: intellikb
          MYSQL_USER: intellikb
          MYSQL_PASSWORD: devpass123
        ports:
          - 3306:3306
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: cp .env.example .env
      - run: pytest tests/ -v --ignore=tests/integration/test_agent_chat.py
```
