"""
TONY Module Configuration - 历史、地理、其他

This module handles:
- 历史 (History)
- 地理 (Geography)
- 其他 (Other)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings


class TONYSettings(BaseAppSettings):
    """TONY模块配置 - 历史、地理、其他"""

    # 模块特定配置
    MODULE_NAME: str = "tony"
    APP_NAME: str = "AI Learning Assistant - TONY Module"
    PORT: int = 6005

    # 支持的学科
    SUBJECTS: List[str] = ["history", "geography", "other"]

    # 日志文件
    LOG_FILE: str = "./logs/tony.log"


@lru_cache()
def get_settings() -> TONYSettings:
    """Get cached TONY settings instance"""
    return TONYSettings()


# 导出settings实例供模块使用
settings = get_settings()
