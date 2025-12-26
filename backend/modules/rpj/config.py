"""
RPJ Module Configuration - 历史、地理、其他

This module handles:
- 历史 (History)
- 地理 (Geography)
- 其他 (Other)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings


class RPJSettings(BaseAppSettings):
    """RPJ模块配置 - 历史、地理、其他"""

    # 模块特定配置
    MODULE_NAME: str = "rpj"
    APP_NAME: str = "AI Learning Assistant - RPJ Module"
    PORT: int = 6001

    # 支持的学科
    SUBJECTS: List[str] = ["chinese", "english", "politics"]

    # 日志文件
    LOG_FILE: str = "./logs/rpj.log"


@lru_cache()
def get_settings() -> RPJSettings:
    """Get cached RPJ settings instance"""
    return RPJSettings()


# 导出settings实例供模块使用
settings = get_settings()
