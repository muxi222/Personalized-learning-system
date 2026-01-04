"""
File Utilities - 文件管理工具
用户文件目录管理和路径生成
"""

import os
import re
import hashlib
from typing import Optional, Tuple
from ..db.models import User

def sanitize_filename(name: str) -> str:
    """
    清理文件名，移除不安全字符

    Args:
        name: 原始文件名

    Returns:
        安全的文件名
    """
    # 移除特殊字符，只保留字母数字和下划线
    name = re.sub(r'[^\w\-_.]', '_', name)
    # 限制长度
    return name[:50]

def get_user_directory_name(username: str, email: str) -> str:
    """
    生成用户专属目录名称

    格式: {username}_{email}
    例如: student001_student@example.com

    Args:
        username: 用户名
        email: 用户邮箱

    Returns:
        用户目录名称
    """
    # 清理用户名和邮箱，确保文件系统安全
    safe_username = sanitize_filename(username)
    safe_email = sanitize_filename(email)
    return f"{safe_username}_{safe_email}"

def get_user_upload_dir(
    base_dir: str,
    user: User,
    file_type: str = "corrections",
    subject: Optional[str] = None,
) -> str:
    """
    获取用户专属上传目录

    目录结构:
    data/uploads/{username_email}/corrections/{subject}/
    data/uploads/{username_email}/questions/{subject}/

    Args:
        base_dir: 基础目录 (如 ./data/uploads)
        user: 用户对象
        file_type: 文件类型 (corrections 或 questions)
        subject: 学科 (可选)

    Returns:
        用户专属目录路径
    """
    # 生成用户目录名
    user_dir_name = get_user_directory_name(user.username, user.email)

    # 构建路径
    if subject:
        path = os.path.join(base_dir, user_dir_name, file_type, subject)
    else:
        path = os.path.join(base_dir, user_dir_name, file_type)

    # 确保目录存在
    os.makedirs(path, exist_ok=True)

    return path

def get_user_file_path(
    base_dir: str,
    user: User,
    file_type: str,
    subject: str,
    filename: str,
) -> str:
    """
    获取用户文件的完整路径

    Args:
        base_dir: 基础目录
        user: 用户对象
        file_type: 文件类型 (corrections/questions)
        subject: 学科
        filename: 文件名

    Returns:
        完整文件路径
    """
    user_dir = get_user_upload_dir(base_dir, user, file_type, subject)
    return os.path.join(user_dir, filename)

def get_user_file_url(
    user: User,
    file_type: str,
    subject: str,
    filename: str,
) -> str:
    """
    生成用户文件的URL路径

    使用用户ID而不是用户名/邮箱，提高安全性

    Args:
        user: 用户对象
        file_type: 文件类型 (corrections/questions)
        subject: 学科
        filename: 文件名

    Returns:
        完整的API URL路径
    """
    return f"/api/v1/ocr/images/{file_type}/{user.id}/{subject}/{filename}"

def calculate_file_hash(content: bytes) -> str:
    """
    计算文件内容的SHA256哈希值

    Args:
        content: 文件内容的字节数据

    Returns:
        SHA256哈希值的十六进制字符串（64字符）
    """
    return hashlib.sha256(content).hexdigest()

def get_filename_from_path(file_path: str) -> str:
    """
    从完整路径中提取文件名

    Args:
        file_path: 完整文件路径

    Returns:
        文件名
    """
    return os.path.basename(file_path)
