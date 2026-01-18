"""
Base Configuration - 所有模块共享的基础配置

所有模块的配置类都应继承此类,并覆盖模块特定的配置项
"""

from functools import lru_cache
from typing import Optional, List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class BaseAppSettings(BaseSettings):
    """
    基础配置类 - 所有模块继承

    共享配置: 数据库、Redis、LLM API、Embedding等
    模块特定: MODULE_NAME, PORT, SUBJECTS(子类覆盖)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ Application (模块特定 - 子类覆盖) ============
    APP_NAME: str = "AI Learning Assistant"
    APP_VERSION: str = "0.1.0"
    MODULE_NAME: str = "base"  # 模块名称(rpj, xmx, wzy, wzm, tony)
    APP_ENV: str = "development"  # development, staging, production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # ============ Server (模块特定 - 子类覆盖) ============
    HOST: str = "0.0.0.0"
    PORT: int = 6100
    WORKERS: int = 1
    RELOAD: bool = True

    # ============ Public API URL (用于生成外部可访问的URL) ============
    # 如果设置了此变量，将使用此URL作为图片等资源的外部访问地址
    # 格式: http://106.63.100.63:30284 或 https://example.com
    # 如果不设置，将使用 HOST:PORT 组合
    PUBLIC_API_BASE_URL: Optional[str] = None

    # ============ Security (共享) ============
    SECRET_KEY: str = "your-super-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # ============ CORS (共享) ============
    CORS_ORIGINS: List[str] | str = ["http://localhost:8000", "http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # ============ Database (共享 - 同一个数据库) ============
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/app.db"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str):
        """
        Ensure async driver is used for SQLite.

        If users accidentally configure `sqlite:///...` (sync driver) while the app uses
        SQLAlchemy AsyncEngine/AsyncSession, it can trigger runtime errors like:
        "greenlet_spawn has not been called; can't call await_only() here".
        """
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s.startswith("sqlite:///") and not s.startswith("sqlite+aiosqlite:///"):
            return "sqlite+aiosqlite:///" + s[len("sqlite:///") :]
        if s.startswith("sqlite:///:memory:") and not s.startswith("sqlite+aiosqlite:///:memory:"):
            return "sqlite+aiosqlite:///:memory:"
        return s

    # ============ Redis (共享 - 使用Key前缀隔离) ============
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PREFIX: str = "learning_assistant:"

    # ============ Vector Store (模块独立路径) ============
    VECTOR_STORE_TYPE: str = "faiss"  # faiss (with BM25 hybrid search)
    VECTOR_STORE_PATH: str = "./data/faiss"
    BM25_INDEX_PATH: str = "./data/bm25"
    VECTOR_COLLECTION_NAME: str = "questions"

    # Hybrid Search Configuration (共享)
    HYBRID_SEARCH_VECTOR_WEIGHT: float = 0.6  # FAISS weight
    HYBRID_SEARCH_BM25_WEIGHT: float = 0.4    # BM25 weight
    HYBRID_SEARCH_SIMILARITY_THRESHOLD: float = 0.55  # Minimum similarity threshold
    HYBRID_SEARCH_TOP_K: int = 20  # Retrieve top K before filtering

    # ============ LLM API Configuration (共享) ============
    # 统一的 LLM API 端点配置（用于访问 Gemini 等模型）
    LLM_API_ENDPOINT: str = "http://35.220.164.252:3888/v1"
    LLM_API_KEY: str = "sk-9U5s6Js2iIq4wAFBQDXFRmaUWoexQpgOiTWQRAHCHoTPVA7u"

    # ============ LLM Resilience / Rate Limit (共享) ============
    # 对 429/5xx/网络抖动做短重试；若上游返回 Retry-After，会优先遵从。
    LLM_RETRY_MAX_ATTEMPTS: int = 3
    LLM_RETRY_BASE_DELAY_SECONDS: float = 0.6
    LLM_RETRY_MAX_DELAY_SECONDS: float = 30.0
    # 单进程内的最大并发（降低 429 发生概率；多进程仍可能触发上游限流）
    LLM_MAX_CONCURRENCY: int = 100

    # ============ Gemini API Configuration (共享) ============
    GEMINI_API_KEY: Optional[str] = None  # 已弃用，使用 LLM_API_KEY 代替
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_THINKING_BUDGET: int = 16384
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash"  # For image generation/editing

    # ============ LLM Configuration (共享) ============
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4-turbo-preview"

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-opus-20240229"

    # Default LLM Provider
    DEFAULT_LLM_PROVIDER: str = "openai"  # openai, anthropic

    # ============ Embedding Configuration (共享) ============
    EMBEDDING_MODEL: str = "text-embedding-3-small"  # OpenAI embedding model
    EMBEDDING_DIMENSION: int = 1536
    LOCAL_EMBEDDING_MODEL: Optional[str] = None  # e.g., "BAAI/bge-large-zh-v1.5"

    # ============ Agent Configuration (共享) ============
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT: int = 120  # seconds

    # ============ MCP (Model Context Protocol) ============
    # Phase 1: retrieval-mcp (Tony first)
    MCP_RETRIEVAL_ENABLED: bool = False
    # Streamable HTTP endpoint, e.g. http://127.0.0.1:7010/mcp
    MCP_RETRIEVAL_URL: Optional[str] = None

    # ============ Task Queue (Celery) (共享Broker,模块独立队列) ============
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ============ Subject-specific Configuration (模块特定 - 子类覆盖) ============
    SUBJECTS: List[str] = []  # 每个模块支持的学科列表

    # ============ Logging (模块特定 - 子类覆盖) ============
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: str = "./logs/app.log"

    # ============ Dynamic Properties (模块独立) ============

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.APP_ENV == "development"

    @property
    def module_redis_prefix(self) -> str:
        """每个模块独立的Redis前缀"""
        return f"{self.REDIS_PREFIX}{self.MODULE_NAME}:"

    @property
    def module_celery_queue(self) -> str:
        """每个模块独立的Celery队列名称"""
        return f"queue_{self.MODULE_NAME}"

    @property
    def module_vector_path(self) -> str:
        """每个模块独立的向量索引路径"""
        return f"{self.VECTOR_STORE_PATH}/{self.MODULE_NAME}"

    @property
    def module_bm25_path(self) -> str:
        """每个模块独立的BM25索引路径"""
        return f"{self.BM25_INDEX_PATH}/{self.MODULE_NAME}"

    # ============ GraphRAG (模块独立路径) ============
    # GraphRAG uses:
    # - a lightweight knowledge graph (`graph.json`)
    # - the existing hybrid retriever (FAISS+BM25) for seed retrieval
    GRAPHRAG_ENABLED: bool = False
    GRAPHRAG_BASE_PATH: str = "./data/training"
    GRAPHRAG_GRAPH_FILENAME: str = "graph.json"

    @property
    def module_graphrag_dir(self) -> str:
        return f"{self.GRAPHRAG_BASE_PATH}/{self.MODULE_NAME}/graphrag"

    @property
    def module_graphrag_graph_path(self) -> str:
        return f"{self.module_graphrag_dir}/{self.GRAPHRAG_GRAPH_FILENAME}"

    # ============ LLM Helper Methods (共享) ============

    def get_llm_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        """Get API key for specified LLM provider"""
        provider = provider or self.DEFAULT_LLM_PROVIDER
        if provider == "openai":
            return self.OPENAI_API_KEY
        elif provider == "anthropic":
            return self.ANTHROPIC_API_KEY
        return None

    def get_llm_model(self, provider: Optional[str] = None) -> str:
        """Get model name for specified LLM provider"""
        provider = provider or self.DEFAULT_LLM_PROVIDER
        if provider == "openai":
            return self.OPENAI_MODEL
        elif provider == "anthropic":
            return self.ANTHROPIC_MODEL
        return self.OPENAI_MODEL

@lru_cache()
def get_base_settings() -> BaseAppSettings:
    """Get cached base settings instance"""
    return BaseAppSettings()
