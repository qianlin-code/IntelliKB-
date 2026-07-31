"""
应用配置 —— pydantic-settings 管理所有环境变量

安全校验：Settings 实例化时通过 @model_validator 校验 secret_key、db_password，
启动时即 fail-fast。
"""
from pathlib import Path
from urllib.parse import quote_plus
from enum import Enum

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 弱密码 / 弱密钥黑名单 —— 模块级 frozenset（公开校验方法）
WEAK_PASSWORDS: frozenset[str] = frozenset({
    "", "admin", "admin123", "root", "root123", "password", "123456",
    "12345678", "1234567890", "changeme", "change-me", "secret",
    "test", "test123", "guest", "user", "qwerty", "abc123", "pass",
    "passwd", "p@ssw0rd", "letmein", "iloveyou", "CHANGE_ME_DB_PASSWORD",
})

WEAK_SECRETS: frozenset[str] = frozenset({
    "", "change-me", "changeme", "secret", "your-secret-key",
    "your-secret", "CHANGE_ME_RANDOM_64_CHARS",
})


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 忽略 .env 中的 Docker 变量 (MYSQL_*, etc.)
    )

    # ── 应用 ──
    APP_NAME: str = "IntelliKB"
    APP_VERSION: str = "1.0.1"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # ── 数据库 ──
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "intellikb"
    DB_PASSWORD: str = ""
    DB_NAME: str = "intellikb"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_TIMEOUT: int = 30

    @property
    def database_url(self) -> str:
        encoded = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+aiomysql://{self.DB_USER}:{encoded}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    # alembic 离线/在线迁移使用的同步 URL
    ALEMBIC_SYNC_URL: str = ""

    # ── Redis ──
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_SOCKET_TIMEOUT: int = 5

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ── JWT ──
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── LLM 占位（Phase 2 启用）──
    LLM_PROVIDER: str = "ollama"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL_NAME: str = "qwen2.5:7b"
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 3

    # ── 本地 Ollama（Phase 6 fallback 专用）──
    # 这两项始终存在，与 LLM_PROVIDER 无关。
    # 当 LLM_PROVIDER=deepseek 等云端 provider 时，fallback 使用此地址连接本地 Ollama。
    # Docker 内用 http://ollama:11434/v1，本地开发用 http://localhost:11434/v1
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_API_KEY: str = "ollama"

    # ── Embedding ──
    # nomic-embed-text: 768 维通用模型，ollama 可直接使用
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIM: int = 768
    # ── Phase 8 P2.2: 多语言 Embedding ──
    # 中文场景推荐 bge-m3 (1024 维)，需先: ollama pull bge-m3
    EMBEDDING_MODEL_ZH: str = "bge-m3"
    EMBEDDING_MODEL_EN: str = "nomic-embed-text"
    # 语言检测模型（用于自动切换 embedding）
    EMBEDDING_AUTO_DETECT_LANG: bool = False  # True=自动检测文档语言并选择对应模型

    # ── 向量库占位 ──
    VECTOR_STORE_BACKEND: str = "chroma"
    CHROMA_PERSIST_DIR: str = str(PROJECT_ROOT / "chroma_data")

    # ── RAG 缓存占位 ──
    RAG_CACHE_TTL_SECONDS: int = 3600
    RAG_CACHE_ENABLED: bool = True

    # ── SSE ──
    SSE_TIMEOUT_SECONDS: int = 300
    SSE_HEARTBEAT_INTERVAL: int = 15
    SSE_PROGRESS_POLL_INTERVAL: float = 1.0  # Phase 2: 进度轮询间隔（秒）

    # ── Phase 2: 混合检索 ──
    HYBRID_BM25_TOP_K: int = 20
    HYBRID_VECTOR_TOP_K: int = 20
    HYBRID_RRF_K: int = 60
    HYBRID_RERANK_TOP_K: int = 5

    # ── Phase 2: 检索相似度阈值 ──
    # 向量检索/纯检索结果低于此阈值视为不相关，直接过滤。
    # 默认 0.55：既能过滤掉无关内容，又能保留弱相关片段。
    SEARCH_SCORE_THRESHOLD: float = 0.55

    # ── Phase 2: Rerank ──
    RERANK_ENABLED: bool = True
    # 通用 Reranker 模型（Phase 8 作为第三级回退）
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # ── Phase 8: 中文 Reranker 升级 ──
    # 第一优先级：中文优化模型（推荐 bge-reranker-base，~1.3GB，6GB VRAM 可运行）
    RERANK_MODEL_ZH: str = "BAAI/bge-reranker-base"
    # 第二级回退：英文通用模型（~200MB）
    RERANK_MODEL_FALLBACK: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # ── Phase 7: Rerank 离线 ──
    # 本地模型缓存目录；scripts/download_reranker.py 预下载到此目录
    RERANK_LOCAL_DIR: str = str(PROJECT_ROOT / "reranker_models")

    # ── Phase 2: Query Rewrite ──
    QUERY_REWRITE_ENABLED: bool = True
    QUERY_REWRITE_CACHE_TTL: int = 300
    QUERY_REWRITE_MAX_TOKENS: int = 256
    # ── Phase 8: 查询重写策略 ──
    # A=resolution: 指代消解（默认，当前行为）
    # B=decomposition: 复杂问题拆解为子查询
    # C=keyword: 核心实体/关键词提取
    QUERY_REWRITE_STRATEGY: str = "A"  # A | B | C

    # ── Phase 3: Agent ──
    AGENT_ENABLED: bool = True
    AGENT_MODEL: str = "qwen2.5:7b"
    AGENT_TIMEOUT_SECONDS: int = 180
    AGENT_MAX_TOOL_ITERATIONS: int = 5

    # ── Phase 3: Conversation ──
    CONVERSATION_MAX_HISTORY_ROUNDS: int = 20
    CONVERSATION_TITLE_LENGTH: int = 30

    # ── Phase 3: SSE Pub/Sub ──
    SSE_PUBSUB_ENABLED: bool = True

    # ── Phase 3: KBMember Cache ──
    MEMBER_CACHE_TTL_SECONDS: int = 60

    # ── Phase 4: Checkpointer ──
    CHECKPOINT_ENABLED: bool = True  # 是否启用 MySQL Checkpointer（False 时回退 MemorySaver）

    # ── Phase 5: Token 流式 ──
    STREAMING_TOKEN_LEVEL: bool = True  # True=方案 A 逐 token SSE；False=节点级降级

    # ── Phase 5: RAG 评测 ──
    RAG_EVAL_ENABLED: bool = True  # True=注册 /eval 路由；False=不注册，请求返回 404

    # ── Phase 5: ReAct ──
    REACT_ENABLED: bool = False  # True=完整 ReAct 循环；False=简化两阶段（fallback）

    # ── Phase 5: 模型 Provider ──
    LLM_PROVIDER: str = "ollama"  # ollama | deepseek | qwen | openai
    CLOUD_MODEL_NAME: str = "deepseek-chat"
    CLOUD_AGENT_MODEL: str = "deepseek-chat"
    CLOUD_BASE_URL: str = ""
    CLOUD_API_KEY: str = ""

    # ── Phase 5: Embedding 超时 ──
    EMBEDDING_TIMEOUT_SECONDS: float = 60.0

    # ── Phase 6: 云端 LLM 确认 ──
    # 显式确认启用云端 LLM；LLM_PROVIDER != ollama 时必须设为 true，否则启动报错
    CLOUD_LLM_CONFIRMED: bool = False

    # ── Phase 6: 成本上限 ──
    DAILY_TOKEN_LIMIT: int = 100000     # 每日 token 消耗上限（0 = 不限制）
    MONTHLY_TOKEN_LIMIT: int = 2000000  # 每月 token 消耗上限（0 = 不限制）

    # ── Phase 6: 云端超时 ──
    CLOUD_TIMEOUT_SECONDS: int = 30  # 云端 LLM 调用超时（秒）

    # ── CORS ──
    CORS_ORIGINS_DEV: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    CORS_ORIGINS_PROD: list[str] = []

    @property
    def cors_origins(self) -> list[str]:
        if self.ENVIRONMENT == Environment.DEVELOPMENT:
            return self.CORS_ORIGINS_DEV
        return self.CORS_ORIGINS_PROD

    # ── 文件上传 ──
    MAX_UPLOAD_SIZE_MB: int = 50
    UPLOAD_DIR: str = str(PROJECT_ROOT / "uploads")
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/markdown", "text/plain", "text/html",
    ]
    # ── Phase 8: 语义分块策略 ──
    # "fixed": RecursiveCharacterTextSplitter（当前行为，向后兼容）
    # "semantic": 按 Markdown 标题/段落/句子边界切分
    CHUNKING_STRATEGY: str = "semantic"  # fixed | semantic

    # ── Phase 8 P2.1: OCR 支持 ──
    # 启用后对扫描版 PDF/图片文件执行 OCR 文字提取
    # 依赖: pip install pytesseract (需额外安装 Tesseract 系统包)
    #       pip install paddleocr (无需系统依赖，推荐)
    OCR_ENABLED: bool = False
    OCR_ENGINE: str = "paddleocr"  # paddleocr | tesseract
    OCR_LANGUAGE: str = "ch"        # ch (中英混合) | chi_sim | eng

    # ── Phase 10: 资源配额 ──
    QUOTA_ENABLED: bool = False
    QUOTA_MAX_KB_PER_USER: int = 10
    QUOTA_MAX_DOCUMENTS_PER_KB: int = 100
    QUOTA_MAX_KB_MEMBERS_PER_KB: int = 20
    QUOTA_MAX_STORAGE_MB_PER_USER: int = 500

    # ── 限流 ──
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX_REQUESTS: int = 60
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    LOGIN_RATE_LIMIT_MAX: int = 5
    LOGIN_RATE_LIMIT_WINDOW: int = 900
    REGISTER_RATE_LIMIT_MAX: int = 10
    REGISTER_RATE_LIMIT_WINDOW: int = 3600

    # ── 日志 ──
    LOG_LEVEL: str = "INFO"

    # ── 管理员 ──
    ADMIN_PASSWORD: str = ""

    # ── 属性 ──
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    # ── 弱密码/弱密钥校验方法 ──
    def is_weak_password(self, p: str) -> bool:
        return p in WEAK_PASSWORDS

    def is_weak_secret(self, s: str) -> bool:
        return s in WEAK_SECRETS

    # ── 安全校验（实例化时执行，fail-fast）──
    @model_validator(mode="after")
    def _validate_security(self):
        if self.is_weak_secret(self.SECRET_KEY):
            raise ValueError(
                f"SECRET_KEY 使用了不安全的值。请在 .env 中设置随机 64 字符密钥。\n"
                f"  生成: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if self.is_weak_password(self.DB_PASSWORD):
            raise ValueError(f"DB_PASSWORD 使用了弱密码 '{self.DB_PASSWORD}'。请在 .env 中设置强密码。")
        if self.ENVIRONMENT != "development":
            if not self.ADMIN_PASSWORD:
                raise ValueError("非开发环境必须设置 ADMIN_PASSWORD")
            if self.is_weak_password(self.ADMIN_PASSWORD):
                raise ValueError(
                    f"ADMIN_PASSWORD '{self.ADMIN_PASSWORD}' 在弱密码黑名单中，请更换。"
                )
        # Phase 5: 云端 provider 必须提供 API Key
        if self.LLM_PROVIDER != "ollama" and not self.CLOUD_API_KEY:
            raise ValueError(
                f"LLM_PROVIDER={self.LLM_PROVIDER} 但 CLOUD_API_KEY 为空。"
                f"请在 .env 中设置 CLOUD_API_KEY，或切换回 LLM_PROVIDER=ollama。"
            )
        # Phase 6: 云端 LLM 必须显式确认（防止误配置产生费用）
        if self.LLM_PROVIDER != "ollama" and not self.CLOUD_LLM_CONFIRMED:
            raise ValueError(
                f"LLM_PROVIDER={self.LLM_PROVIDER} 但 CLOUD_LLM_CONFIRMED 不为 true。\n"
                f"在 .env 中设置 CLOUD_LLM_CONFIRMED=true 以确认启用云端 LLM"
                f"（会产生 API 费用）。\n"
                f"若不确定，请设置 LLM_PROVIDER=ollama 使用本地模型。"
            )
        return self


settings = Settings()
