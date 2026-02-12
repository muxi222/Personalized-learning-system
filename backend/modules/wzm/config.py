"""
WZM Module Configuration - 化学、其他

This module handles:
- 化学 (Chemistry)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings

class WZMSettings(BaseAppSettings):
    """WZM模块配置 - 化学"""

    # 模块特定配置
    MODULE_NAME: str = "wzm"
    APP_NAME: str = "AI Learning Assistant - WZM Module"
    PORT: int = 6004

    # 支持的学科
    SUBJECTS: List[str] = ["chemistry"]

    # 日志文件
    LOG_FILE: str = "./logs/wzm.log"

@lru_cache()
def get_settings() -> WZMSettings:
    """Get cached WZM settings instance"""
    return WZMSettings()

# 导出settings实例供模块使用
settings = get_settings()
