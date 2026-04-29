# backend/modules/rpj/config.py
"""
RPJ Module Configuration - 语文、英语、道法

Supported subjects:
- 语文 (Chinese)
- 英语 (English)
- 道德与法治 (Morality & Law)
"""
import os
from pathlib import Path
from typing import List, Optional
from functools import lru_cache

from backend.core.base_config import BaseAppSettings


class RPJSettings(BaseAppSettings):
    """RPJ模块配置 - 语文、英语、道法"""

    # 模块基本信息
    MODULE_NAME: str = "rpj"
    APP_NAME: str = "AI Learning Assistant - RPJ Module"
    APP_VERSION: str = "1.0.0"
    PORT: int = 6001
    DEBUG: bool = os.getenv("RPJ_DEBUG", "false").lower() == "true"

    # API配置
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:6001"]

    # 支持的学科
    SUBJECTS: List[str] = ["chinese", "english", "morality"]

    # 日志配置
    LOG_LEVEL: str = os.getenv("RPJ_LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: str = os.getenv("RPJ_LOG_FILE", "./logs/rpj.log")

    # 模块数据目录
    MODULE_DATA_DIR: Path = Path(__file__).parent.parent / "data"
    
    # 向量存储路径
    module_vector_path: Path = MODULE_DATA_DIR / "vectors"
    
    # BM25索引路径
    module_bm25_path: Path = MODULE_DATA_DIR / "bm25_index"
    
    # GraphRAG图路径
    module_graphrag_graph_path: Path = MODULE_DATA_DIR / "graphrag" / "knowledge_graph.json"
    
    # 学科分类数据路径
    module_taxonomy_path: Path = MODULE_DATA_DIR / "taxonomy"

    # LLM配置
    LLM_API_ENDPOINT: str = os.getenv("LLM_API_ENDPOINT", "http://localhost:8000/v1")
    LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")
    
    # Gemini配置（用于OCR）
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # 文本推理模型配置
    RPJ_TEXT_REASONING_MODELS: str = os.getenv(
        "RPJ_TEXT_REASONING_MODELS", 
        "gemini-2.5-flash,qwen2.5-7b-instruct"
    )
    RPJ_TEXT_REASONING_TIMEOUT_SECONDS: int = int(
        os.getenv("RPJ_TEXT_REASONING_TIMEOUT_SECONDS", "300")
    )
    
    # 个性化模型配置
    PERSONAL_MODEL_ENABLED_RPJ: bool = os.getenv("PERSONAL_MODEL_ENABLED_RPJ", "false").lower() == "true"
    PERSONAL_MODEL_API_BASE_RPJ: str = os.getenv(
        "PERSONAL_MODEL_API_BASE_RPJ", 
        "http://localhost:8002/v1"
    )
    PERSONAL_MODEL_MODEL_RPJ: str = os.getenv("PERSONAL_MODEL_MODEL_RPJ", "rpj-dpo")
    
    # GraphRAG配置
    GRAPHRAG_ENABLED: bool = os.getenv("GRAPHRAG_ENABLED_RPJ", "false").lower() == "true"
    
    # 数据库表前缀
    DB_TABLE_PREFIX: str = "rpj_"
    
    # Celery配置
    CELERY_BROKER_URL: str = os.getenv("RPJ_CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = os.getenv("RPJ_CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    
    @property
    def module_celery_queue(self) -> str:
        """Celery队列名称"""
        return f"{self.MODULE_NAME}_queue"
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.DEBUG or os.getenv("ENVIRONMENT", "development") == "development"
    
    class Config:
        env_file = ".env"
        env_prefix = "RPJ_"
        case_sensitive = True


@lru_cache()
def get_settings() -> RPJSettings:
    """获取缓存的RPJ配置实例"""
    return RPJSettings()


# 导出配置实例
settings = get_settings()

# 确保数据目录存在
os.makedirs(settings.MODULE_DATA_DIR, exist_ok=True)
os.makedirs(settings.module_vector_path, exist_ok=True)
os.makedirs(settings.module_bm25_path, exist_ok=True)
os.makedirs(settings.module_graphrag_graph_path.parent, exist_ok=True)
os.makedirs(settings.module_taxonomy_path, exist_ok=True)