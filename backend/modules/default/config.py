"""
Default Module Configuration - 默认模块配置

This module handles cross-subject queries and operations:
- 所有学科 (All subjects)
- 跨学科统计 (Cross-subject statistics)
- 不区分学科的查询 (Subject-agnostic queries)
"""

from functools import lru_cache
from typing import List
from backend.core.base_config import BaseAppSettings


class DefaultSettings(BaseAppSettings):
    """默认模块配置 - 处理所有学科"""

    # 模块特定配置
    MODULE_NAME: str = "default"
    APP_NAME: str = "AI Learning Assistant - Default Module"
    PORT: int = 6100  # 使用 6100（6000 在浏览器不安全端口黑名单中）

    # 支持的学科：所有学科
    SUBJECTS: List[str] = [
        "chinese", "english", "politics",  # RPJ
        "economics",                        # XMX
        "math", "physics",                  # WZY
        "chemistry",                        # WZM
        "history", "geography", "other",    # TONY
    ]

    # 日志文件
    LOG_FILE: str = "./logs/default.log"


@lru_cache()
def get_settings() -> DefaultSettings:
    """Get cached Default settings instance"""
    return DefaultSettings()


# 导出settings实例供模块使用
settings = get_settings()
