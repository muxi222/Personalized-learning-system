"""
RPJ Module Configuration - 历史、地理、其他

This module handles:
- 历史 (History)
- 地理 (Geography)
- 其他 (Other)
"""
import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings

class RPJSettings(BaseSettings):
    # 模块名称
    MODULE_NAME: str = "rpj"
    
    # 模块数据目录
    MODULE_DATA_DIR: Path = Path(__file__).parent.parent / "data"
    
    # 向量存储路径
    module_vector_path: Path = MODULE_DATA_DIR / "vectors"
    
    # BM25索引路径
    module_bm25_path: Path = MODULE_DATA_DIR / "bm25_index"
    
    # GraphRAG图路径
    module_graphrag_graph_path: Path = MODULE_DATA_DIR / "graphrag" / "knowledge_graph.json"
    
    # 个性化模型配置
    personal_model_enabled: bool = os.getenv("PERSONAL_MODEL_ENABLED_RPJ", "false").lower() == "true"
    personal_model_api_base: str = os.getenv("PERSONAL_MODEL_API_BASE_RPJ", "http://127.0.0.1:8001/v1")
    personal_model_model: str = os.getenv("PERSONAL_MODEL_MODEL_RPJ", "rpj-dpo")
    
    # GraphRAG是否启用
    GRAPHRAG_ENABLED: bool = os.getenv("GRAPHRAG_ENABLED_RPJ", "false").lower() == "true"
    
    # 数据库表前缀
    DB_TABLE_PREFIX: str = "rpj_"
    
    class Config:
        env_file = ".env"
        env_prefix = "RPJ_"


# 创建配置实例
settings = RPJSettings()

# 确保数据目录存在
os.makedirs(settings.MODULE_DATA_DIR, exist_ok=True)
os.makedirs(settings.module_vector_path, exist_ok=True)
os.makedirs(settings.module_bm25_path, exist_ok=True)
os.makedirs(settings.module_graphrag_graph_path.parent, exist_ok=True)

class RPJSettings(BaseAppSettings):
    """RPJ模块配置 - 语文,英语,道法"""

    # 模块特定配置
    MODULE_NAME: str = "rpj"
    APP_NAME: str = "AI Learning Assistant - RPJ Module"
    PORT: int = 6001

    # 支持的学科
    SUBJECTS: List[str] = ["chinese","english","politics"]

    # 日志文件
    LOG_FILE: str = "./logs/rpj.log"

@lru_cache()
def get_settings() -> RPJSettings:
    """Get cached RPJ settings instance"""
    return RPJSettings()

# 导出settings实例供模块使用
settings = get_settings()
