"""
Application Configuration
配置驱动设计 - 所有核心参数通过环境变量/配置文件管理
"""

from functools import lru_cache
from typing import Optional, List
from pydantic import field_validator, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============ Application ============
    APP_NAME: str = "AI Learning Assistant"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"  # development, staging, production
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # ============ Server ============
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    RELOAD: bool = True

    # ============ Security ============
    SECRET_KEY: str = "your-super-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    # ============ CORS ============
    CORS_ORIGINS: List[str] | str = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # ============ Database ============
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/app.db"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    # ============ Redis ============
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PREFIX: str = "learning_assistant:"

    # ============ Vector Store (FAISS + BM25) ============
    VECTOR_STORE_TYPE: str = "faiss"  # faiss (with BM25 hybrid search)
    VECTOR_STORE_PATH: str = "./data/faiss"
    BM25_INDEX_PATH: str = "./data/bm25"
    VECTOR_COLLECTION_NAME: str = "questions"

    # Hybrid Search Configuration
    HYBRID_SEARCH_VECTOR_WEIGHT: float = 0.6  # FAISS weight
    HYBRID_SEARCH_BM25_WEIGHT: float = 0.4    # BM25 weight
    HYBRID_SEARCH_SIMILARITY_THRESHOLD: float = 0.55  # Minimum similarity threshold
    HYBRID_SEARCH_TOP_K: int = 20  # Retrieve top K before filtering

    # ============ LLM API Configuration ============
    # 统一的 LLM API 端点配置（用于访问 Gemini 等模型）
    LLM_API_ENDPOINT: str = "http://35.220.164.252:3888/v1"
    LLM_API_KEY: str = "sk-9U5s6Js2iIq4wAFBQDXFRmaUWoexQpgOiTWQRAHCHoTPVA7u"

    # ============ Gemini API Configuration ============
    GEMINI_API_KEY: Optional[str] = None  # 已弃用，使用 LLM_API_KEY 代替
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_THINKING_BUDGET: int = 16384
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash"  # For image generation/editing

    # ============ LLM Configuration ============
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4-turbo-preview"

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-opus-20240229"

    # Default LLM Provider
    DEFAULT_LLM_PROVIDER: str = "openai"  # openai, anthropic

    # ============ Embedding Configuration ============
    EMBEDDING_MODEL: str = "text-embedding-3-small"  # OpenAI embedding model
    EMBEDDING_DIMENSION: int = 1536
    LOCAL_EMBEDDING_MODEL: Optional[str] = None  # e.g., "BAAI/bge-large-zh-v1.5"

    # ============ Agent Configuration ============
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT: int = 120  # seconds

    # ============ Task Queue (Celery) ============
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ============ Subject-specific Prompts ============
    SUBJECTS: List[str] = ["math", "physics", "chemistry", "biology", "english"]

    # ============ Logging ============
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: str = "./logs/app.log"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

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
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()

