#!/usr/bin/env python3
"""
Batch fix imports for XMX module agents
"""
import os
import re

# Agent files to fix
agent_files = [
    'question_intake_agent.py',
    'ocr_agent.py',
    'similar_question_agent.py',
    'tasks.py',
]

# Import replacement rules
replacements = [
    # Relative imports from .state → absolute imports
    (r'from \.state import', 'from backend.core.agents.state import'),

    # Relative imports from .prompts → absolute imports
    (r'from \.prompts import', 'from backend.core.agents.prompts import'),

    # Services imports
    (r'from \.\.services\.', 'from backend.core.services.'),

    # DB imports
    (r'from \.\.db\.', 'from backend.core.db.'),

    # CRUD imports
    (r'from \.\.crud\.', 'from backend.core.crud.'),

    # Schemas imports
    (r'from \.\.schemas\.', 'from backend.core.schemas.'),

    # Core config → Module config
    (r'from \.\.core\.config import', 'from backend.modules.xmx.config import'),

    # Celery app
    (r'from \.\.core\.celery_app import', 'from backend.modules.xmx.celery_app import'),
]

for filename in agent_files:
    filepath = filename
    if not os.path.exists(filepath):
        print(f"⚠️  File not found: {filepath}")
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # Apply all replacement rules
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    # Check if modified
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fixed imports in {filename}")
    else:
        print(f"ℹ️  No changes needed for {filename}")

print("\n🎉 Agent import fixing complete!")
