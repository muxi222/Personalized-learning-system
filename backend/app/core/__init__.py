"""
Core module - Configuration, middleware, and utilities
"""

from .config import settings  # noqa: F401
from . import bcrypt_compat  # noqa: F401  # ensure compatibility patch is applied

__all__ = ["settings"]

