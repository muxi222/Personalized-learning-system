"""
WZY Module Configuration - 数学、物理

This module handles:
- 数学 (Maths)
- 物理 (Physics)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings

class WZYSettings(BaseAppSettings):
    """WZY模块配置 - 数学、物理"""

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
