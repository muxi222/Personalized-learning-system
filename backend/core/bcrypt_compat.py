"""
Bcrypt Compatibility Patch
修复 bcrypt 4.0+ 与 passlib 的兼容性问题

bcrypt 4.1.0+ 移除了 __about__ 属性，导致 passlib 无法读取版本信息。
此补丁在导入 passlib 之前修复 bcrypt 模块，添加缺失的 __about__ 属性。
"""

import bcrypt
import logging

logger = logging.getLogger(__name__)

# 检查并修复 bcrypt 模块的兼容性问题
if not hasattr(bcrypt, '__about__'):
    try:
        # 尝试从 __version__ 获取版本信息
        version = getattr(bcrypt, '__version__', 'unknown')

        # 创建一个简单的 __about__ 对象
        class _BcryptAbout:
            __version__ = version

        # 将 __about__ 添加到 bcrypt 模块
        bcrypt.__about__ = _BcryptAbout()

        logger.debug(f"Applied bcrypt compatibility patch: version={version}")
    except Exception as e:
        logger.warning(f"Failed to apply bcrypt compatibility patch: {e}")
        # 如果修复失败，创建一个最小化的 __about__ 对象以避免错误
        class _BcryptAbout:
            __version__ = 'unknown'
        bcrypt.__about__ = _BcryptAbout()
