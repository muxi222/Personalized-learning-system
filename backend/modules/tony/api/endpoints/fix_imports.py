#!/usr/bin/env python3
"""
Batch fix imports for TONY module endpoints
"""
import os
import re

# 当前目录的所有.py文件（除了这个脚本本身和__init__.py）
endpoint_files = [
    'questions.py',
    'ocr.py',
    'corrections.py',
    'learning.py',
    'guidance.py',
    'image_files.py',
    'tasks.py',
    'feedback.py',
]

# Import替换规则
replacements = [
    # 相对导入 -> 绝对导入
    (r'from \.\.\.\.db\.session import', 'from backend.core.db.session import'),
    (r'from \.\.\.\.db\.models import', 'from backend.core.db.models import'),
    (r'from \.\.\.\.crud import', 'from backend.core.crud import'),
    (r'from \.\.\.\.crud\.', 'from backend.core.crud.'),
    (r'from \.\.\.\.schemas\.', 'from backend.core.schemas.'),
    (r'from \.\.\.\.services\.', 'from backend.core.services.'),
    (r'from \.\.\.\.core\.config import', 'from backend.modules.tony.config import'),
    (r'from \.\.deps import', 'from backend.modules.tony.api.deps import'),

    # 处理agents导入（需要指向模块的agents）
    (r'from \.\.\.\.agents\.', 'from backend.modules.tony.agents.'),
]

for filename in endpoint_files:
    filepath = filename
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 应用所有替换规则
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    # 检查是否有修改
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fixed imports in {filename}")
    else:
        print(f"ℹ️  No changes needed for {filename}")

print("\n🎉 Import fixing complete!")
