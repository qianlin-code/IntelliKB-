# IntelliKB Phase 1 —— 知识库管理 + 文档上传 + RAG 检索 实施计划

## 修订历史

| 版本 | 日期 | 修订人 | 主要内容 |
|------|------|--------|----------|
| v1.0 | 2026-07-28 | Claude | 初版计划 |
| v1.1 | 2026-07-29 | Claude | S1 Docker volume / S2 Ollama 网络 / S3 Chunk 软删除 / S4 LLM 降级 / M1 魔数校验 / M2 重复上传 / M3 分块说明 / M4 文档元信息 / M5 Vite 代理限制 / M6 测试覆盖 |
| v1.2 | 2026-07-29 | Claude | Embedding 模型切换: bge-small-zh(384维) → nomic-embed-text(768维)，bge-small-zh 在 Ollama 注册表中不可用 |

---

## 0. 前置条件与架构约束

### 0.1 Phase 0 已有基础

| 组件 | 状态 | 说明 |
|------|:--:|------|
| FastAPI 应用入口 + lifespan | ✅ | `app/main.py`，alembic 自动迁移 + Redis 初始化 |
| SQLAlchemy 2.0 async + MySQL | ✅ | `app/core/database.py`，`async_session_factory` + `get_db()` |
| Alembic 同步迁移 | ✅ | `alembic/`，首次迁移 `sys_user` 已就绪 |
| Redis 异步客户端 | ✅ | `app/core/redis_client.py`，`cache_get/set/delete` + `blacklist_set` |
| JWT 双 token 认证 | ✅ | `app/core/security.py`，access + refresh，blacklist 登出 |
| API Key bcrypt 认证 | ✅ | `app/depends/auth.py`，JWT + X-API-Key 双通道 |
| 统一响应格式 | ✅ | `app/core/response.py`，`APIResponse.success/error/created` |
| 全局异常处理 | ✅ | `app/core/exceptions.py`，trace_id 全链路 |
| 结构化日志 | ✅ | `app/core/logging.py`，JSON 格式 + TraceIdFilter |
| 中间件三件套 | ✅ | CORS + TraceMiddleware + LoggingMiddleware |
| 前端骨架 | ✅ | Vue 3 + Element Plus，Login + Dashboard + 404 |
| 测试基础设施 | ✅ | `pytest + pytest-asyncio + httpx.ASGITransport` |

### 0.2 Phase 1 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Embedding 方案 | Ollama API (`nomic-embed-text`) | 768 维通用模型，Ollama 可直接使用 |
| 向量库 | ChromaDB，每知识库独立 Collection | 天然隔离，查询无需 kb_id filter |
| 文档解析 | pdfplumber (PDF) + python-docx (DOCX) + 内置 (MD/TXT) | 轻量、纯 Python，避免 `unstructured` 重型依赖 |
| 文本分块 | `langchain-text-splitters` | RecursiveCharacterTextSplitter，成熟稳定 |
| RAG 检索 | 向量相似度 Top-K + 可选 LLM 生成 | 非流式，Phase 2 升级混合检索 + Rerank + SSE 流式 |
| Collection 命名 | `kb_{kb_id}` | 创建 KB 时建 Collection，删除 KB 时删 Collection |
| 文档解析模式 | 同步（请求内完成） | Phase 1 文档量小，BackgroundTasks + SSE 进度推迟到 Phase 2 |

### 0.3 RAG 管线（Phase 1 vs Phase 2）

```
Phase 1（本阶段）:
  用户问题 → Embedding → Chroma 向量相似度 Top-K → [可选] LLM 拼接生成 → JSON 返回

Phase 2（下一阶段）:
  用户问题 → Query Rewrite → BM25 + 向量混合检索 → RRF 融合 → Cross-encoder Rerank
           → Redis 缓存 → LLM 流式生成 → SSE 打字机效果
```

---

## 1. 依赖扩展

### 1.1 requirements.txt 追加

```text
# ── Phase 1: 知识库 + 文档 + RAG ──
chromadb>=0.5,<1.0
langchain-text-splitters>=0.3,<1.0
pdfplumber>=0.11
python-docx>=1.1
openai>=1.0,<2.0              # Ollama 兼容 OpenAI API（embedding + chat）
```

> **依赖说明**：
> - `chromadb`：Chroma 向量数据库（Python 客户端，自带嵌入式 SQLite3 存储）
> - `langchain-text-splitters`：仅用 `RecursiveCharacterTextSplitter`，不引入完整 langchain
> - `pdfplumber`：PDF 文本提取（比 PyPDF2 更准确，支持表格）
> - `python-docx`：DOCX 文本提取
> - `openai`：通过 Ollama 兼容 API 调用 embedding + chat，统一客户端

### 1.2 Ollama 模型准备

```bash
# 拉取 embedding 模型（768 维通用模型）
ollama pull nomic-embed-text

# 确认 LLM 模型可用（Phase 0 已配置）
ollama pull qwen2.5:7b
```

---

## 2. 数据模型扩展

### 2.1 ER 关系

```
sys_user (已有)         sys_kb                    sys_document
┌──────────────┐       ┌──────────────────┐       ┌─────────────────────┐
│ id           │──┐    │ id               │──┐    │ id                  │
│ username     │  │    │ owner_id (FK)    │  │    │ kb_id (FK)          │
│ ...          │  │    │ name             │  │    │ filename            │
└──────────────┘  │    │ description      │  │    │ file_type           │
                  └───>│ is_public        │  └───>│ file_size           │
                       │ chunk_size       │       │ status              │
                       │ chunk_overlap    │       │ chunk_count         │
                       │ embedding_model  │       │ error_message       │
                       │ deleted_at       │       │ deleted_at          │
                       │ created_at       │       │ created_at          │
                       │ updated_at       │       │ updated_at          │
                       └──────────────────┘       └─────────────────────┘
                                                              │
                                                              │ 1:N
                                                              ▼
                                                  sys_chunk
                                                  ┌─────────────────────┐
                                                  │ id                  │
                                                  │ document_id (FK)    │
                                                  │ chunk_index         │
                                                  │ content (TEXT)      │
                                                  │ token_count         │
                                                  │ deleted_at          │
                                                  │ created_at          │
                                                  └─────────────────────┘
```

### 2.2 SQL 表定义

```sql
-- 知识库
CREATE TABLE sys_kb (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL COMMENT '所有者用户 ID',
    name VARCHAR(200) NOT NULL COMMENT '知识库名称',
    description TEXT COMMENT '描述',
    is_public BOOLEAN DEFAULT FALSE COMMENT '是否公开',
    chunk_size INT DEFAULT 500 COMMENT '分块大小（字符）',
    chunk_overlap INT DEFAULT 50 COMMENT '分块重叠（字符）',
    embedding_model VARCHAR(100) DEFAULT 'nomic-embed-text' COMMENT 'Embedding 模型名（v1.2 切换）',
    deleted_at DATETIME DEFAULT NULL COMMENT '软删除',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_kb_owner (owner_id),
    INDEX idx_kb_public (is_public),
    CONSTRAINT fk_kb_owner FOREIGN KEY (owner_id) REFERENCES sys_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库';

-- 文档
CREATE TABLE sys_document (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kb_id INT NOT NULL COMMENT '所属知识库 ID',
    filename VARCHAR(500) NOT NULL COMMENT '原始文件名',
    file_type VARCHAR(20) NOT NULL COMMENT '文件类型: pdf/docx/md/txt',
    file_size INT DEFAULT 0 COMMENT '文件大小（字节）',
    status ENUM('uploading','parsing','chunking','indexing','done','error') DEFAULT 'uploading' COMMENT '处理状态',
    chunk_count INT DEFAULT 0 COMMENT '分块数量',
    error_message TEXT COMMENT '错误信息',
    deleted_at DATETIME DEFAULT NULL COMMENT '软删除',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_doc_kb (kb_id),
    INDEX idx_doc_kb_status (kb_id, status),
    INDEX idx_doc_status (status),
    CONSTRAINT fk_doc_kb FOREIGN KEY (kb_id) REFERENCES sys_kb(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档';

-- 文档分块（S3: 软删除一致 — 无 ON DELETE CASCADE，应用层同步删除标记）
CREATE TABLE sys_chunk (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_id INT NOT NULL COMMENT '所属文档 ID',
    chunk_index INT NOT NULL COMMENT '分块序号（从 0 开始）',
    content TEXT NOT NULL COMMENT '分块文本内容',
    token_count INT DEFAULT 0 COMMENT 'Token 数量估算',
    deleted_at DATETIME DEFAULT NULL COMMENT '删除时间（与 Document 同步软删除）',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_chunk_doc (document_id),
    CONSTRAINT fk_chunk_doc FOREIGN KEY (document_id) REFERENCES sys_document(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档分块';
```

### 2.3 SQLAlchemy 模型（`app/models/`）

**`app/models/knowledge_base.py`**：
- 继承 `Base, TimestampMixin`，额外 `SoftDeleteMixin` 或直接 `deleted_at` 字段
- `owner_id: Mapped[int]` → `User.id`
- `name`, `description`, `is_public`, `chunk_size`, `chunk_overlap`, `embedding_model`

**`app/models/document.py`**：
- `Document`：继承 `Base, TimestampMixin, SoftDeleteMixin`
- `kb_id`, `filename`, `file_type`, `file_size`, `status`, `chunk_count`, `error_message`
- `DocumentChunk`：继承 `Base, SoftDeleteMixin`（**S3**: chunk 与 Document 同步软删除，无 ON DELETE CASCADE）
- `document_id`, `chunk_index`, `content`, `token_count`

### 2.4 模型注册

`app/models/__init__.py` 更新为导入所有模型（保证 Alembic autogenerate 能发现）：

```python
from app.models.user import User                          # noqa: F401
from app.models.knowledge_base import KnowledgeBase       # noqa: F401
from app.models.document import Document, DocumentChunk   # noqa: F401
```

---

## 3. 后端 API 设计

### 3.1 路由前缀

```
/api/v1/knowledge-bases    → knowledge_bases.py
/api/v1/documents          → documents.py
/api/v1/qa                 → qa.py
```

所有端点（除公开 KB 列表外）需要认证，支持 JWT Bearer + X-API-Key 双通道。

### 3.2 知识库 API（6 端点）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/v1/knowledge-bases` | 创建知识库 | 登录用户 |
| `GET` | `/api/v1/knowledge-bases` | 我的知识库列表 | 登录用户 |
| `GET` | `/api/v1/knowledge-bases/{kb_id}` | 知识库详情 | owner 或 public |
| `PUT` | `/api/v1/knowledge-bases/{kb_id}` | 更新知识库 | owner |
| `DELETE` | `/api/v1/knowledge-bases/{kb_id}` | 删除知识库（软删除 + 清理向量） | owner |
| `GET` | `/api/v1/knowledge-bases/{kb_id}/stats` | 知识库统计（文档数/分块数） | owner 或 public |

### 3.3 文档 API（5 端点）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/v1/documents/upload` | 上传文档（multipart） | kb owner |

> **M2**: Phase 1 同名文件上传会创建新记录，不自动覆盖旧文档。文档去重推迟到 Phase 2。

| `GET` | `/api/v1/documents` | 文档列表（?kb_id=1） | kb owner 或 public kb |
| `GET` | `/api/v1/documents/{doc_id}` | 文档详情 + 分块列表 | kb owner |
| `DELETE` | `/api/v1/documents/{doc_id}` | 删除文档（+向量清理） | kb owner |
| `GET` | `/api/v1/documents/{doc_id}/chunks` | 文档分块列表（含内容） | kb owner |

### 3.4 RAG API（2 端点）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/v1/qa/search` | 向量检索（仅返回 chunks，不生成） | kb owner 或 public kb |
| `POST` | `/api/v1/qa/ask` | RAG 问答（检索 + LLM 生成） | kb owner 或 public kb |

### 3.5 认证集成

Phase 1 所有端点复用 Phase 0 的 `get_current_user_or_api_key` 依赖：

```python
# 知识库权限校验辅助
async def get_kb_or_403(kb_id: int, user: User, db: AsyncSession) -> KnowledgeBase:
    """获取知识库，校验权限（owner 或 public），否则 403"""
    kb = await kb_repo.get_by_id(db, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    if kb.owner_id != user.id and not kb.is_public:
        raise ForbiddenError("无权访问该知识库")
    return kb

async def get_kb_owner_or_403(kb_id: int, user: User, db: AsyncSession) -> KnowledgeBase:
    """获取知识库，校验 owner 权限，否则 403"""
    kb = await kb_repo.get_by_id(db, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    if kb.owner_id != user.id:
        raise ForbiddenError("仅知识库所有者可执行此操作")
    return kb
```

---

## 4. Core 服务设计

### 4.1 EmbeddingService（`app/services/embedding_service.py`）

```python
class EmbeddingService:
    """通过 Ollama 兼容 API 生成文本向量"""

    def __init__(self, base_url: str, model: str, dim: int):
        self.client = openai.AsyncOpenAI(
            base_url=f"{base_url}/v1",
            api_key="ollama",  # Ollama 不需要真实 key
        )
        self.model = model
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        """单文本向量化"""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化"""
        ...
```

> **关键实现**：
> - 使用 `openai.AsyncOpenAI`，base_url 指向 Ollama（`http://localhost:11434/v1`）
> - 调用 `client.embeddings.create(model=self.model, input=text)`
> - 批量请求减少网络往返

### 4.2 VectorStoreService（`app/services/vector_store.py`）

```python
class VectorStoreService:
    """ChromaDB 向量存储，每知识库独立 Collection"""

    def __init__(self, persist_dir: str):
        self.client = chromadb.PersistentClient(path=persist_dir)

    def _collection_name(self, kb_id: int) -> str:
        return f"kb_{kb_id}"

    def get_or_create_collection(self, kb_id: int):
        """获取或创建知识库专属 Collection"""
        ...

    async def add_chunks(
        self, kb_id: int, chunk_ids: list[int],
        embeddings: list[list[float]], documents: list[str],
        metadatas: list[dict]
    ) -> None:
        """批量写入向量，metadata 含 document_id + filename（M4）"""
        ...

    async def search(
        self, kb_id: int, query_embedding: list[float],
        top_k: int = 5
    ) -> list[dict]:
        """向量相似度检索，返回 [{chunk_id, content, score, document_id, metadata}, ...]（M4）"""
        ...

    async def delete_chunks(self, kb_id: int, chunk_ids: list[int]) -> None:
        """删除指定 chunk 向量"""
        ...

    async def delete_collection(self, kb_id: int) -> None:
        """删除知识库 Collection（删除 KB 时调用）"""
        ...
```

> **关键实现**：
> - ChromaDB `PersistentClient`，数据持久化到 `CHROMA_PERSIST_DIR`
> - 向量 ID = chunk.id（架构文档 A12 策略：向量 ID 直接用 MySQL 主键）
> - `search()` 调用 `collection.query(query_embeddings=[...], n_results=top_k)`
> - ChromaDB 操作是同步的，通过 `asyncio.to_thread()` 包装为异步

### 4.3 DocService（`app/services/doc_service.py`）

```python
class DocService:
    """文档生命周期管理：上传 → 解析 → 分块 → 向量化 → 存储"""

    SUPPORTED_TYPES = {"pdf", "docx", "md", "txt"}

    async def upload_and_process(
        self, kb_id: int, file: UploadFile, user_id: int
    ) -> Document:
        """完整流程：保存文件 → 创建记录 → 解析 → 分块 → 嵌入 → 存向量"""
        1. 校验文件类型（扩展名 + MIME）
        2. 校验文件大小（≤ MAX_UPLOAD_SIZE_MB）
        3. 读取文件内容（bytes）
        4. 校验文件魔数（_validate_file_magic）  ← M1 新增
        5. 创建 Document 记录（status='parsing'）
        6. 提取文本（_extract_text）
        7. 更新 status='chunking'
        8. 文本分块（_split_chunks）
        9. 更新 status='indexing'
        10. 批量写入 sys_chunk 表 → flush 获取 chunk.id
        11. 批量生成 embeddings
        12. 写入 Chroma 向量库（M4: metadata 含 document_id + filename）
        13. 更新 status='done', chunk_count
        14. 异常时 status='error', 记录 error_message
        → 返回 Document

    def _validate_file_magic(self, file_type: str, content: bytes) -> None:
        """M1: 文件魔数校验，防止扩展名伪装"""
        if file_type == "pdf":
            if not content.startswith(b"%PDF"):
                raise BusinessError("文件格式异常或已损坏：PDF 文件头无效")
        elif file_type == "docx":
            # DOCX 是 ZIP 格式，必须包含 [Content_Types].xml
            import zipfile, io
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    if "[Content_Types].xml" not in zf.namelist():
                        raise BusinessError("文件格式异常或已损坏：DOCX 缺少必要文件")
            except zipfile.BadZipFile:
                raise BusinessError("文件格式异常或已损坏：DOCX 不是有效 ZIP 文件")
        elif file_type in ("txt", "md"):
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                raise BusinessError("文件格式异常或已损坏：TXT/MD 无法以 UTF-8 解码")

    def _extract_text(self, file_type: str, content: bytes) -> str:
        """按文件类型调用对应解析器"""
        pdf → pdfplumber.open(io.BytesIO(content))
        docx → Document(io.BytesIO(content))  # python-docx
        md/txt → content.decode("utf-8")

    def _split_chunks(self, text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
        """langchain RecursiveCharacterTextSplitter 分块"""
        ...

    async def delete_document(self, doc_id: int) -> None:
        """删除文档 + 清理向量 + MySQL 软删除（S3: chunk 同步软删除）"""
        1. 查 sys_chunk WHERE document_id = doc_id AND deleted_at IS NULL → chunk_ids
        2. Chroma 删除向量（按 chunk_ids）
        3. MySQL 软删除 DocumentChunk（SET deleted_at = now() WHERE document_id = doc_id）
        4. MySQL 软删除 Document（deleted_at = now()）
```

### 4.4 RAGService（`app/services/rag_service.py`）

```python
class RAGService:
    """RAG 检索 + 生成"""

    async def search(
        self, kb_id: int, question: str, top_k: int = 5
    ) -> list[dict]:
        """纯检索：embedding → Chroma 相似度 → 返回 chunks"""
        1. embedding_service.embed(question)
        2. vector_store.search(kb_id, embedding, top_k)
        3. 返回 [{chunk_id, content, score}, ...]

    async def ask(
        self, kb_id: int, question: str, top_k: int = 5
    ) -> dict:
        """RAG 问答：检索 + LLM 生成（S4: LLM 失败降级）"""
        1. chunks = await self.search(kb_id, question, top_k)
        2. 构建 prompt（System + Context + Question）
        3. try:
             调用 LLM（Ollama openai 兼容 chat API）
             返回 {answer, sources: [...], llm_error: false}
           except Exception:
             logger.warning("LLM 调用失败，降级返回检索结果")
             返回 {answer: "LLM 服务暂时不可用，已返回检索到的相关片段，请自行参考。",
                   sources: chunks, llm_error: true}

    def _build_prompt(self, question: str, chunks: list[dict]) -> str:
        """构建 RAG prompt 模板"""
        context = "\n\n---\n\n".join(
            f"[来源 {i+1}]\n{c['content']}" for i, c in enumerate(chunks)
        )
        return f"""你是一个智能知识库助手。请根据以下参考资料回答用户问题。

参考资料：
{context}

用户问题：{question}

请用中文回答。如果参考资料不足以回答问题，请明确说明。回答时引用来源编号。"""
```

### 4.5 KBService（`app/services/kb_service.py`）

```python
class KBService:
    """知识库 CRUD"""

    async def create(self, user_id: int, data: KBCreate) -> KnowledgeBase:
        """创建知识库 + 初始化 Chroma Collection"""
        1. 创建 MySQL 记录
        2. vector_store.get_or_create_collection(kb.id)
        → 返回 KB

    async def list_my(self, user_id: int, page, page_size) -> tuple[list[KB], int]:
        """我的知识库列表（owner_id = user_id）"""

    async def get(self, kb_id: int) -> KnowledgeBase | None:
        """获取单个知识库"""

    async def update(self, kb_id: int, data: KBUpdate) -> KnowledgeBase:
        """更新知识库元信息。
        M3: 修改 chunk_size/chunk_overlap 仅影响后续上传文档，已有文档不会自动重分块。"""

    async def delete(self, kb_id: int) -> None:
        """软删除知识库 + 删除 Chroma Collection + 清理文档（S3: chunk 同步软删除）"""
        1. 查所有文档 → 逐个清理向量
        2. 删除 Chroma Collection
        3. 软删除所有 DocumentChunk（SET deleted_at = now() WHERE document_id IN (...)）
        4. 软删除所有文档（SET deleted_at = now() WHERE kb_id = kb_id）
        5. 软删除知识库（SET deleted_at = now() WHERE id = kb_id）
```

---

## 5. Schemas 设计

### 5.1 KnowledgeBase Schemas

```python
class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = False
    chunk_size: int = Field(default=500, ge=100, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=500)

class KBUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    is_public: bool | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=2000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)

class KBResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None
    is_public: bool
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class KBStats(BaseModel):
    kb_id: int
    document_count: int
    chunk_count: int
    total_size_bytes: int
```

### 5.2 Document Schemas

```python
class DocumentResponse(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class DocumentUploadResponse(BaseModel):
    doc_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    message: str

class ChunkResponse(BaseModel):
    id: int
    chunk_index: int
    content: str
    token_count: int
```

### 5.3 QA Schemas

```python
class SearchRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)

class SearchResult(BaseModel):
    chunk_id: int
    document_id: int        # M4: 检索结果所属文档 ID
    content: str
    score: float

class SearchResponse(BaseModel):
    results: list[SearchResult]

class AskRequest(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)

class AskResponse(BaseModel):
    answer: str
    sources: list[SearchResult]
    llm_error: bool = False    # S4: LLM 调用失败时为 True，前端据此展示降级提示
```

---

## 6. Repository 设计

### 6.1 KBRepository

```python
class KBRepository:
    async def create(self, db: AsyncSession, **kwargs) -> KnowledgeBase
    async def get_by_id(self, db: AsyncSession, kb_id: int) -> KnowledgeBase | None
    async def list_by_owner(self, db: AsyncSession, owner_id: int, skip: int, limit: int) -> list[KnowledgeBase]
    async def count_by_owner(self, db: AsyncSession, owner_id: int) -> int
    async def update(self, db: AsyncSession, kb: KnowledgeBase, **kwargs) -> KnowledgeBase
    async def soft_delete(self, db: AsyncSession, kb: KnowledgeBase) -> None
```

### 6.2 DocumentRepository

```python
class DocumentRepository:
    async def create(self, db: AsyncSession, **kwargs) -> Document
    async def get_by_id(self, db: AsyncSession, doc_id: int) -> Document | None
    async def list_by_kb(self, db: AsyncSession, kb_id: int, skip: int, limit: int) -> list[Document]
    async def count_by_kb(self, db: AsyncSession, kb_id: int) -> int
    async def update(self, db: AsyncSession, doc: Document, **kwargs) -> Document
    async def soft_delete(self, db: AsyncSession, doc: Document) -> None
    async def create_chunks_batch(self, db: AsyncSession, chunks: list[dict]) -> list[DocumentChunk]
    async def get_chunks_by_doc(self, db: AsyncSession, doc_id: int) -> list[DocumentChunk]
    async def get_chunk_ids_by_doc(self, db: AsyncSession, doc_id: int) -> list[int]
    async def delete_chunks_by_doc(self, db: AsyncSession, doc_id: int) -> None
    async def get_chunks_by_kb(self, db: AsyncSession, kb_id: int) -> list[DocumentChunk]
    async def count_chunks_by_kb(self, db: AsyncSession, kb_id: int) -> int
    async def total_size_by_kb(self, db: AsyncSession, kb_id: int) -> int
```

> **注意**：Repository 层不包含异步网络调用（Embedding/Chroma），Service 层编排业务流程。

---

## 7. 前端页面设计

### 7.1 新增文件清单

```
frontend/src/
  components/
    AppLayout.vue             ← 侧边栏 + 顶栏布局壳
  views/
    knowledge/
      KBList.vue              ← 知识库列表（卡片网格）
      KBCreate.vue            ← 创建知识库（对话框或独立页）
      KBDetail.vue            ← 知识库详情 + 文档列表
    documents/
      DocUpload.vue           ← 文档上传组件（拖拽 + 按钮）
    qa/
      QAPage.vue              ← RAG 问答页（搜索 + 结果展示）
  api/
    knowledgeBase.ts          ← KB CRUD API 封装
    document.ts               ← 文档 API 封装
    qa.ts                     ← QA API 封装
  store/
    knowledgeBase.ts          ← KB 状态管理
  types/
    index.ts                  ← 追加 Phase 1 类型定义
  router/
    index.ts                  ← 追加路由：/kbs, /kb/:id, /qa/:kbId
```

#### M5: Vite 代理大文件上传限制

修改现有 `frontend/vite.config.ts` 的 proxy 配置：

```typescript
// vite.config.ts — proxy 增加 body 限制
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  }
}
```

> **M5 说明**：Vite dev server 的 `http-proxy` 默认不限制请求 body size，
> 实际限制来自后端 `MAX_UPLOAD_SIZE_MB`（50MB）。
> 若生产部署在 Nginx 后面，需额外配置 `client_max_body_size 50m;`。
> `vite.config.ts` 无需代码改动，此项为文档说明。

### 7.2 布局壳 `AppLayout.vue`

```
┌──────────────────────────────────────────────┐
│  🧠 IntelliKB    [知识库] [问答]    👤 admin │  ← 顶栏
├────────────┬─────────────────────────────────┤
│  侧边栏     │                                 │
│  · 我的知识库│        <router-view />           │
│  · 知识库A   │                                 │
│  · 知识库B   │                                 │
│  + 创建知识库│                                 │
├────────────┴─────────────────────────────────┤
│  v0.2.0 · IntelliKB 智能知识库平台             │  ← 底栏
└──────────────────────────────────────────────┘
```

- **顶栏**：Logo + 主导航（知识库管理 / 问答 / API 管理）+ 用户下拉菜单
- **侧边栏**：知识库列表（el-menu），可折叠；底部"创建知识库"按钮
- **底栏**：版本号 + 版权信息
- **内容区**：`<router-view />`

### 7.3 路由扩展

```typescript
// router/index.ts 新增路由
{
  path: '/kbs',
  component: AppLayout,            // 带侧边栏的布局
  meta: { requiresAuth: true },
  children: [
    { path: '', name: 'KBList', component: KBList, meta: { title: '知识库管理' } },
    { path: ':kbId', name: 'KBDetail', component: KBDetail, meta: { title: '知识库详情' } },
  ]
},
{
  path: '/qa/:kbId',
  component: AppLayout,
  meta: { requiresAuth: true },
  children: [
    { path: '', name: 'QAPage', component: QAPage, meta: { title: '智能问答' } },
  ]
},
```

### 7.4 KBList 页面（知识库列表）

- **卡片网格**（el-row + el-col）：每个 KB 一张卡片
  - 名称、描述（截断 2 行）、公开/私有标签
  - 文档数、分块数统计
  - "进入问答" / "管理文档" / "删除" 按钮
- **顶部操作栏**：搜索 + "创建知识库" 按钮
- **创建对话框**：el-dialog 内嵌表单（名称、描述、是否公开、分块配置）
- **空状态**：无知识库时显示引导提示

### 7.5 KBDetail 页面（知识库详情 + 文档列表）

- **知识库信息卡片**：名称、描述、公开状态、创建时间
- **文档列表表格**（el-table）：文件名、类型、大小、状态（tag）、分块数、上传时间
  - 状态标签颜色：uploading/parsing/chunking/indexing（warning）、done（success）、error（danger）
- **上传区域**（el-upload）：拖拽上传，支持 `.pdf,.docx,.md,.txt`
  - 上传成功后刷新列表
- **操作按钮**：编辑 KB、删除 KB、进入问答

### 7.6 QAPage 页面（RAG 问答）

- **顶部**：知识库选择器（下拉）+ 当前 KB 信息
- **搜索模式切换**：`el-radio-group` — "仅检索" / "RAG 问答"
- **输入区**：el-input textarea + 发送按钮（Ctrl+Enter）
- **结果区**：
  - **仅检索模式**：卡片列表，每张卡片展示 chunk 内容 + 相关度分数进度条
  - **RAG 问答模式**：Markdown 渲染的回答 + 折叠的参考来源面板
- **空状态**：输入问题开始搜索

### 7.7 状态管理（Pinia Store）

```typescript
// store/knowledgeBase.ts
export const useKBStore = defineStore('kb', () => {
  const kbList = ref<KB[]>([])
  const currentKB = ref<KB | null>(null)
  const loading = ref(false)

  async function fetchKBList() { ... }
  async function fetchKB(kbId: number) { ... }
  async function createKB(data: KBCreate) { ... }
  async function updateKB(kbId: number, data: KBUpdate) { ... }
  async function deleteKB(kbId: number) { ... }

  return { kbList, currentKB, loading, fetchKBList, fetchKB, createKB, updateKB, deleteKB }
})
```

### 7.8 类型扩展（`types/index.ts`）

```typescript
// Phase 1 新增类型
export interface KnowledgeBase {
  id: number; owner_id: number; name: string; description: string | null
  is_public: boolean; chunk_size: number; chunk_overlap: number
  embedding_model: string; created_at: string; updated_at: string
}
export interface KBCreate { name: string; description?: string; is_public?: boolean; chunk_size?: number; chunk_overlap?: number }
export interface KBUpdate { name?: string; description?: string; is_public?: boolean; chunk_size?: number; chunk_overlap?: number }
export interface KBStats { kb_id: number; document_count: number; chunk_count: number; total_size_bytes: number }
export interface DocumentInfo { id: number; kb_id: number; filename: string; file_type: string; file_size: number; status: string; chunk_count: number; error_message: string | null; created_at: string; updated_at: string }
export interface DocumentUploadResponse { doc_id: number; filename: string; file_type: string; file_size: number; status: string; message: string }
export interface ChunkInfo { id: number; chunk_index: number; content: string; token_count: number }
export interface SearchRequest { kb_id: number; question: string; top_k?: number }
export interface SearchResult { chunk_id: number; document_id: number; content: string; score: number }
export interface SearchResponse { results: SearchResult[] }
export interface AskRequest { kb_id: number; question: string; top_k?: number }
export interface AskResponse { answer: string; sources: SearchResult[]; llm_error?: boolean }
```

---

## 8. 配置文件变更

### 8.1 config.py 追加

```python
# 文件上传目录（新增）
UPLOAD_DIR: str = str(PROJECT_ROOT / "uploads")

# v1.2: EMBEDDING_DIM=768 / EMBEDDING_MODEL=nomic-embed-text
# (bge-small-zh 在 Ollama 注册表中不可用，已切换)
# LLM_BASE_URL 已存在，EmbeddingService 复用此配置
# CHROMA_PERSIST_DIR 已存在（chroma_data），无需变更
```

### 8.2 main.py 变更

```python
# lifespan startup 追加：
# 1. 创建 uploads 目录（若不存在）
# 2. 确认 Chroma 持久化目录存在

# lifespan shutdown 无需额外变更（Chroma 自带持久化）
```

### 8.3 docker-compose.yml 变更（S1 + S2）

**S1 Docker 持久化 volume**：

```yaml
# app 服务增加 volumes
services:
  app:
    # ... 已有配置 ...
    volumes:
      - app-uploads:/app/uploads          # S1: 上传文件持久化
      - chroma-data:/app/chroma_data      # S1: 向量库持久化

# 文件底部增加 volume 声明
volumes:
  app-uploads:
  chroma-data:
```

**S2 Ollama 网络配置**：

```yaml
# app 服务增加 extra_hosts（Docker 容器访问宿主机 Ollama）
services:
  app:
    # ... 已有配置 ...
    extra_hosts:
      - "host.docker.internal:host-gateway"  # S2: 容器访问宿主机 Ollama
```

### 8.4 .env.example 变更（S2）

```ini
# S2: Ollama 地址注释改为多行说明
# 本地开发：http://localhost:11434/v1
# Docker 部署（Windows/Mac）：http://host.docker.internal:11434/v1
# Docker 部署（Linux 增加 ollama 服务）：http://ollama:11434/v1
LLM_BASE_URL=http://localhost:11434/v1
```

---

## 9. alembic 迁移

```bash
# 生成迁移
alembic revision --autogenerate -m "phase1: sys_kb + sys_document + sys_chunk"

# 应用迁移
alembic upgrade head
```

---

## 10. 文件创建顺序

```
Phase 1 共需创建/修改 ~39 个文件：

 1. requirements.txt                          ← 追加 5 个依赖
 2. app/config.py                             ← 追加 UPLOAD_DIR
 3. app/models/__init__.py                    ← 追加模型导入
 4. app/models/knowledge_base.py              ← KnowledgeBase 模型
 5. app/models/document.py                    ← Document + DocumentChunk 模型
 6. alembic revision --autogenerate           ← 自动生成迁移脚本
 7. alembic upgrade head                      ← 执行迁移

 8. app/schemas/knowledge_base.py             ← KB Pydantic schemas
 9. app/schemas/document.py                   ← Document Pydantic schemas
10. app/schemas/qa.py                         ← QA Pydantic schemas

11. app/repositories/knowledge_base.py        ← KBRepository
12. app/repositories/document.py              ← DocumentRepository

13. app/services/embedding_service.py         ← EmbeddingService
14. app/services/vector_store.py              ← VectorStoreService
15. app/services/kb_service.py                ← KBService
16. app/services/doc_service.py               ← DocService
17. app/services/rag_service.py               ← RAGService

18. app/depends/auth.py                       ← 追加 get_kb_or_403 / get_kb_owner_or_403

19. app/api/v1/knowledge_bases.py             ← KB CRUD 端点
20. app/api/v1/documents.py                   ← Document 端点
21. app/api/v1/qa.py                          ← QA 端点

22. app/api/v1/__init__.py                    ← 注册新路由

23. app/main.py                               ← 添加 uploads 目录创建

24. tests/conftest.py                          ← 新增 EmbeddingService mock fixture
25. tests/test_kb.py                           ← M6: KB CRUD 测试
26. tests/test_document.py                     ← M6: Document 上传/列表/删除测试
27. scripts/seed_data.py                      ← 追加示例 KB + 文档

── 前端 12 files ──

28. frontend/src/components/AppLayout.vue
29. frontend/src/views/knowledge/KBList.vue
30. frontend/src/views/knowledge/KBDetail.vue
31. frontend/src/views/qa/QAPage.vue
32. frontend/src/api/knowledgeBase.ts
33. frontend/src/api/document.ts
34. frontend/src/api/qa.ts
35. frontend/src/store/knowledgeBase.ts
36. frontend/src/types/index.ts              ← 追加类型
37. frontend/src/router/index.ts              ← 追加路由
38. frontend/src/App.vue                      ← 需要调整以支持 AppLayout
39. frontend/src/views/Dashboard.vue          ← 更新导航链接
```

---

## 11. 验证步骤

### 11.1 后端 API 验证

```bash
# ── 前置：登录获取 Token ──
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo3","password":"test1234"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

# ── V1: 创建知识库 ──
curl -s -X POST http://localhost:8000/api/v1/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"测试知识库","description":"Phase 1 验收用","is_public":true}'
# → 201 {"code":201,"data":{"id":1,"name":"测试知识库",...}}

# ── V2: 获取知识库列表 ──
curl -s http://localhost:8000/api/v1/knowledge-bases \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"code":200,"data":{"items":[...],"total":1}}

# ── V3: 获取知识库详情 ──
curl -s http://localhost:8000/api/v1/knowledge-bases/1 \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"code":200,"data":{"id":1,...}}

# ── V4: 更新知识库 ──
curl -s -X PUT http://localhost:8000/api/v1/knowledge-bases/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"测试知识库(已更新)"}'
# → 200

# ── V5: 上传文档（MD） ──
echo "# 测试文档\n\n## 简介\nFastAPI 是一个现代 Web 框架。\n\n## 特性\n- 自动文档\n- 异步支持" > /tmp/test_upload.md

curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/test_upload.md" \
  -F "kb_id=1"
# → 201 {"code":201,"data":{"doc_id":1,"status":"done",...}}

# ── V6: 文档列表 ──
curl -s "http://localhost:8000/api/v1/documents?kb_id=1" \
  -H "Authorization: Bearer $TOKEN"
# → 200 包含上述文档

# ── V7: 文档详情 ──
curl -s http://localhost:8000/api/v1/documents/1 \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"code":200,"data":{"id":1,"status":"done","chunk_count":N}}

# ── V8: 文档分块列表 ──
curl -s http://localhost:8000/api/v1/documents/1/chunks \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"code":200,"data":{"chunks":[{...},{...}]}}

# ── V9: RAG 检索（仅搜索） ──
curl -s -X POST http://localhost:8000/api/v1/qa/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question":"什么是 FastAPI？","top_k":3}'
# → 200 {"code":200,"data":{"results":[{...score>0, document_id:1...}]}}

# ── V10: RAG 问答（检索 + 生成，S4: LLM 不可用时 llm_error=true） ──
curl -s -X POST http://localhost:8000/api/v1/qa/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kb_id":1,"question":"FastAPI 有哪些特性？","top_k":3}'
# → 200 {"code":200,"data":{"answer":"FastAPI 的主要特性包括...","sources":[...],"llm_error":false}}

# ── V11: 知识库统计 ──
curl -s http://localhost:8000/api/v1/knowledge-bases/1/stats \
  -H "Authorization: Bearer $TOKEN"
# → 200 {"code":200,"data":{"kb_id":1,"document_count":1,...}}

# ── V12: 删除文档 ──
curl -s -X DELETE http://localhost:8000/api/v1/documents/1 \
  -H "Authorization: Bearer $TOKEN"
# → 200 确认删除（含向量清理）

# ── V13: 删除知识库 ──
curl -s -X DELETE http://localhost:8000/api/v1/knowledge-bases/1 \
  -H "Authorization: Bearer $TOKEN"
# → 200 确认删除（含 Collection + 文档 + 向量清理）
```

### 11.2 RAG 端到端验证

```bash
# 1. 创建知识库
KB_ID=$(curl -s -X POST http://localhost:8000/api/v1/knowledge-bases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"验收知识库","is_public":true}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")

# 2. 上传测试文档（包含可验证的特定信息）
cat > /tmp/e2e_test.md << 'EOF'
# IntelliKB 验收测试文档

## 产品信息
IntelliKB 是一个基于 RAG 技术的智能知识库平台。
当前最新版本为 v0.2.0，代号 "Phoenix"。

## 核心功能
1. 多格式文档解析：支持 PDF、DOCX、Markdown、TXT
2. 向量化检索：基于 ChromaDB 和 nomic-embed-text 模型（768 维）
3. RAG 智能问答：检索增强生成的端到端问答

## 部署要求
- Python 3.11+
- MySQL 8.0
- Redis 7
- Ollama（可选，用于本地 LLM）
EOF

curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/e2e_test.md" \
  -F "kb_id=$KB_ID"

# 3. 检索验证（应命中"Phoenix"相关信息）
curl -s -X POST http://localhost:8000/api/v1/qa/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"kb_id\":$KB_ID,\"question\":\"IntelliKB 的代号是什么？\",\"top_k\":3}"
# → 结果应包含 "Phoenix"

# 4. 问答验证
curl -s -X POST http://localhost:8000/api/v1/qa/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"kb_id\":$KB_ID,\"question\":\"IntelliKB 有哪些核心功能？\",\"top_k\":3}"
# → answer 应包含 "多格式文档解析"、"向量化检索"、"RAG 智能问答"
```

### 11.3 前端验证

```bash
cd frontend
npm run dev
```

验证页面：
1. `http://localhost:5173/login` → 登录
2. `http://localhost:5173/kbs` → 知识库列表（应有"创建知识库"按钮）
3. 创建知识库 → 卡片列表中显示
4. 点击知识库 → 详情页（文档列表为空）
5. 上传 `.md` 文档 → 状态变为 "done"
6. `http://localhost:5173/qa/{kb_id}` → 输入问题 → 查看检索结果 / RAG 回答

### 11.4 M6 测试覆盖

```python
# tests/conftest.py 追加 mock fixture
@pytest_asyncio.fixture(scope="module")
async def mock_embedding_and_vector():
    """
    M6: 绕过 EmbeddingService + VectorStoreService 的真实网络调用。
    使用 monkeypatch 替换为哑实现（返回固定向量 / 空操作）。
    """
    ...

# tests/test_kb.py
class TestKnowledgeBase:
    """KB CRUD 集成测试（M6）"""
    async def test_create_kb_201(self, client):     # POST /knowledge-bases → 201
        ...
    async def test_list_kb_200(self, client):       # GET /knowledge-bases → 200
        ...
    async def test_get_kb_200(self, client):        # GET /knowledge-bases/{id} → 200
        ...
    async def test_update_kb_200(self, client):     # PUT /knowledge-bases/{id} → 200
        ...
    async def test_delete_kb_200(self, client):     # DELETE /knowledge-bases/{id} → 200
        ...
    async def test_non_owner_cannot_delete(self, client):  # 403
        ...
    async def test_public_kb_accessible(self, client):     # 200（非 owner 可读）
        ...

# tests/test_document.py
class TestDocument:
    """Document 上传/列表/删除 测试（M6，mock embedding + vector）"""
    async def test_upload_md_document_201(self, client, monkeypatch):
        """上传 .md 文档 → 201，status='done'""" ...
    async def test_upload_invalid_extension_400(self, client):
        """上传 .exe → 400""" ...
    async def test_upload_magic_mismatch_400(self, client, monkeypatch):
        """M1: 伪装扩展名上传 → 400""" ...
    async def test_list_documents_200(self, client):
        """GET /documents?kb_id=1 → 200""" ...
    async def test_delete_document_200(self, client):
        """DELETE /documents/{id} → 200（含 chunk 软删除）""" ...
```

> **mock 策略**：`conftest.py` 中通过 `monkeypatch.setattr` 替换
> `EmbeddingService.embed` / `EmbeddingService.embed_batch`（返回 `[0.0]*768`哑向量，匹配 nomic-embed-text 维度）
> 和 `VectorStoreService.add_chunks` / `VectorStoreService.search` / `VectorStoreService.delete_chunks`
> （空操作或返回预设结果），避免测试依赖 Ollama 和 ChromaDB 真实服务。

---

## 12. 风险与简化

## 12. 风险与简化

| 风险 | 应对 |
|------|------|
| ChromaDB PersistentClient 并发限制 | Phase 1 单用户场景可接受，Phase 3 迁移到 Chroma Server 模式 |
| Ollama embedding 延迟（首次需加载模型） | 启动时预热（调用一次 embed），后续 < 100ms |
| ollama bge-small-zh 未安装 | 启动检查 + 日志提示 `ollama pull nomic-embed-text` |
| pdfplumber 对复杂 PDF 解析不佳 | Phase 1 接受，后续可换 `unstructured` |
| Windows ChromaDB SQLite3 文件锁 | 单进程 OK，多 worker 需 Chroma Server |

### 简化项（故意推迟到后续阶段）

| 推迟项 | 阶段 |
|--------|:--:|
| BackgroundTasks 异步解析 + SSE 进度推送 | Phase 2 |
| KBMember 权限表（owner/editor/viewer） | Phase 2 |
| Query Rewrite 查询改写 | Phase 2 |
| BM25 + 向量混合检索 + RRF 融合 | Phase 2 |
| Cross-encoder Rerank | Phase 2 |
| SSE 流式生成 | Phase 2 |
| RAG 检索缓存（Redis） | Phase 2 |
| 文档解析进度 Redis Pub/Sub（多 Worker） | Phase 3 |
| BaseVectorStore 抽象（Chroma/Milvus 切换） | Phase 3 |

---

## 13. 验收标准

| # | 验收项 | 通过条件 |
|---|--------|---------|
| ✅1 | KB CRUD | 创建/列表/详情/更新/删除 正常，Chroma Collection 联动 |
| ✅2 | 文档上传 | PDF/DOCX/MD/TXT 四种格式上传成功，解析 → 分块 → 向量化全流程 |
| ✅3 | 文档管理 | 列表/详情/分块查看/删除（含向量清理） |
| ✅4 | RAG 检索 | 输入问题 → 返回相关 chunks（含相似度分数） |
| ✅5 | RAG 问答 | 检索 + LLM 生成 → 回答引用来源 |
| ✅6 | 知识库隔离 | KB A 的文档不会出现在 KB B 的检索结果中 |
| ✅7 | 权限校验 | 非 owner 无法修改/删除他人 KB；非公开 KB 不可被他人访问 |
| ✅8 | 软删除 | KB + Document + Chunk 三层同步软删除（S3），Chroma 数据同步清理 |
| ✅9 | 魔数校验 | 上传伪装扩展名文件被拒绝，返回明确错误信息（M1） |
| ✅10 | LLM 降级 | Ollama 不可用时 RAG 问答降级返回检索结果 + llm_error=true（S4） |
| ✅11 | 检索元信息 | search 结果包含 document_id 用于前端定位源文档（M4） |
| ✅12 | 前端页面 | 布局壳 + KB 列表 + 文档管理 + QA 页面可交互 |
| ✅13 | API 文档 | Swagger UI 新增端点全部可见可测试 |
| ✅14 | 认证兼容 | 所有新端点支持 JWT Bearer 和 X-API-Key 两种认证 |
| ✅15 | 日志链路 | trace_id 正常透传（请求头 X-Trace-ID + 日志 JSON trace_id 字段） |
| ✅16 | 测试覆盖 | test_kb.py + test_document.py 通过，mock embedding/vector（M6） |
