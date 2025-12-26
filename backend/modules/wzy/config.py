"""
WZY Module Configuration - 历史、地理、其他

This module handles:
- 历史 (History)
- 地理 (Geography)
- 其他 (Other)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings


class WZYSettings(BaseAppSettings):
    """WZY模块配置 - 历史、地理、其他"""

    # 模块特定配置
    MODULE_NAME: str = "wzy"
    APP_NAME: str = "AI Learning Assistant - WZY Module"
    PORT: int = 6003

    # 支持的学科
    SUBJECTS: List[str] = ["math", "physics"]

    # 日志文件
    LOG_FILE: str = "./logs/wzy.log"


@lru_cache()
def get_settings() -> WZYSettings:
    """Get cached WZY settings instance"""
    return WZYSettings()


# 导出settings实例供模块使用
settings = get_settings()
