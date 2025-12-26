#!/usr/bin/env python3
"""
简化学生模块代码脚本

作用: 将rpj/xmx/wzy/wzm模块的API endpoints和agents代码简化为框架版本
保留: TONY模块作为完整参考实现
"""

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
STUDENT_MODULES = ["rpj", "xmx", "wzy", "wzm"]
REFERENCE_MODULE = "tony"

# 需要简化的文件映射
FILES_TO_SIMPLIFY = {
    # API Endpoints
    "api/endpoints/ocr.py": "OCR批改API",
    "api/endpoints/corrections.py": "批改历史API",
    "api/endpoints/learning.py": "学习建议API",
    "api/endpoints/guidance.py": "学习指导API",
    "api/endpoints/image_files.py": "图片文件服务API",
    "api/endpoints/tasks.py": "任务状态API",
    "api/endpoints/feedback.py": "用户反馈API",
    # Agents
    "agents/question_intake_agent.py": "错题录入Agent",
    "agents/ocr_agent.py": "OCR识别Agent",
    "agents/similar_question_agent.py": "相似题目推荐Agent",
}


def create_simplified_file(module: str, relative_path: str, description: str):
    """为学生模块创建简化版文件"""
    source_file = PROJECT_ROOT / "backend" / "modules" / REFERENCE_MODULE / relative_path
    target_file = PROJECT_ROOT / "backend" / "modules" / module / relative_path

    if not source_file.exists():
        print(f"⚠️  参考文件不存在: {source_file}")
        return

    # 读取TONY模块的完整实现
    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 生成简化版内容
    simplified_content = generate_simplified_content(module, relative_path, description, content)

    # 写入目标文件
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(simplified_content)

    print(f"✅ 已创建: {target_file.relative_to(PROJECT_ROOT)}")


def generate_simplified_content(module: str, relative_path: str, description: str, original_content: str) -> str:
    """生成简化版代码内容"""

    # 提取文件类型
    if relative_path.startswith("api/endpoints/"):
        return generate_simplified_api_endpoint(module, relative_path, description)
    elif relative_path.startswith("agents/"):
        return generate_simplified_agent(module, relative_path, description)
    else:
        return original_content


def generate_simplified_api_endpoint(module: str, relative_path: str, description: str) -> str:
    """生成简化版API endpoint"""

    endpoint_name = relative_path.split('/')[-1].replace('.py', '')
    module_upper = module.upper()
    module_subjects_map = {
        "rpj": "chinese, english, politics",
        "xmx": "economics",
        "wzy": "math, physics",
        "wzm": "chemistry",
    }
    subjects = module_subjects_map.get(module, "unknown")

    template = f'''"""
{description} ({module_upper}模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/{REFERENCE_MODULE}/api/endpoints/{endpoint_name}.py

{module_upper}模块支持的学科: {subjects}
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.modules.{module}.api.deps import get_current_user_id
from backend.modules.{module}.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def validate_subject(subject: str) -> None:
    """验证学科是否属于{module_upper}模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{{subject}}' is not supported by {module_upper} module. "
                   f"Supported subjects: {{settings.SUBJECTS}}"
        )


# ============================================================
# TODO: 学生需要实现以下API endpoints
# ============================================================
#
# 请参考完整实现: backend/modules/{REFERENCE_MODULE}/api/endpoints/{endpoint_name}.py
#
# 实现步骤:
# 1. 复制TONY模块对应文件的函数签名和路由装饰器
# 2. 保留学科验证逻辑 (validate_subject)
# 3. 实现业务逻辑（数据库查询、Agent调用等）
# 4. 返回正确的响应数据
#
# 提示:
# - 所有数据库操作使用 backend/core/crud/ 中的函数
# - 所有Agent操作使用 backend/modules/{module}/agents/ 中的类
# - 所有Schema使用 backend/core/schemas/ 中的定义
# ============================================================


# TODO: 在这里添加endpoint实现
# 示例:
# @router.get("/example")
# async def example_endpoint():
#     \"\"\"示例端点\"\"\"
#     return {{"message": "学生TODO: 实现此endpoint"}}
'''

    return template


def generate_simplified_agent(module: str, relative_path: str, description: str) -> str:
    """生成简化版Agent"""

    agent_name = relative_path.split('/')[-1].replace('.py', '').replace('_', ' ').title().replace(' ', '')
    module_upper = module.upper()

    template = f'''"""
{description} ({module_upper}模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心Agent逻辑的实现。
完整实现请参考: backend/modules/{REFERENCE_MODULE}/{relative_path}
"""

import logging
from typing import Dict, Any
from backend.core.agents.base_agent import BaseAgent
from backend.modules.{module}.config import settings

logger = logging.getLogger(__name__)


class {agent_name}(BaseAgent):
    """
    {description}

    TODO: 学生需要实现以下功能
    1. 继承自 BaseAgent，使用 subject 验证
    2. 实现核心处理逻辑
    3. 使用 LangGraph 构建工作流
    4. 返回处理结果

    参考实现: backend/modules/{REFERENCE_MODULE}/{relative_path}
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        logger.info(f"[{{settings.MODULE_NAME.upper()}}] 初始化 {agent_name}")

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        处理主逻辑

        TODO: 学生需要实现此方法

        参数:
            **kwargs: 根据Agent类型不同而不同

        返回:
            Dict[str, Any]: 处理结果

        实现步骤:
        1. 验证输入参数
        2. 调用subject验证 (已在BaseAgent中实现)
        3. 构建LangGraph工作流
        4. 执行Agent逻辑
        5. 返回结果

        参考: backend/modules/{REFERENCE_MODULE}/{relative_path}
        """
        # ============ TODO: 实现Agent逻辑 ============
        logger.warning(f"[{{settings.MODULE_NAME.upper()}}] {agent_name}.process() 需要学生实现")

        return {{
            "success": False,
            "message": "学生TODO: 实现{agent_name}的process方法"
        }}
'''

    return template


def main():
    print("=" * 80)
    print("简化学生模块代码")
    print("=" * 80)
    print()
    print(f"学生模块: {', '.join(STUDENT_MODULES)}")
    print(f"参考模块: {REFERENCE_MODULE} (保持完整)")
    print()

    for module in STUDENT_MODULES:
        print(f"\\n处理模块: {module.upper()}")
        print("-" * 40)

        for relative_path, description in FILES_TO_SIMPLIFY.items():
            create_simplified_file(module, relative_path, description)

    print()
    print("=" * 80)
    print("✅ 所有学生模块已简化完成")
    print("=" * 80)
    print()
    print("下一步:")
    print("1. 学生阅读 backend/modules/tony/ 中的完整实现")
    print("2. 学生实现 backend/modules/rpj/, xmx/, wzy/, wzm/ 中的TODO部分")
    print("3. 参考 TONY 模块的代码结构和实现方式")
    print()


if __name__ == "__main__":
    main()
