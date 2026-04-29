#!/usr/bin/env python3
"""
Test script to verify Personal Model configuration for WZM module
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from backend.core.services.personal_model_service import get_personal_model_service
from backend.core.base_config import get_base_settings

async def main():
    print("=" * 60)
    print("Testing Personal Model Configuration for WZM Module")
    print("=" * 60)

    # Get settings
    settings = get_base_settings()
    module = "wzm"

    print(f"\n1. Configuration Check:")
    print(f"   - Module: {module}")
    print(f"   - Enabled: {settings.personal_model_enabled_for(module)}")
    print(f"   - API Base: {settings.personal_model_api_base_for(module)}")
    print(f"   - Model: {settings.personal_model_model_for(module)}")
    print(f"   - Timeout: {settings.personal_model_timeout_for(module)}s")

    # Get service
    svc = get_personal_model_service(module)

    print(f"\n2. Service Properties:")
    print(f"   - Enabled: {svc.enabled}")
    print(f"   - Default Model: {svc.default_model}")

    # Test connection
    print(f"\n3. Testing Connection to vLLM...")
    try:
        models = await svc.list_models()
        print(f"   ✓ Connection successful!")
        print(f"   - Available models: {len(models)}")
        for m in models:
            model_id = m.get("id", "unknown")
            parent = m.get("parent")
            print(f"     • {model_id}" + (f" (parent: {parent})" if parent else ""))
    except Exception as e:
        print(f"   ✗ Connection failed: {e}")
        return 1

    # Test model resolution
    print(f"\n4. Testing Model Resolution:")
    subjects = ["chemistry", "math", "physics"]
    for subject in subjects:
        try:
            resolved = await svc.resolve_model_for_subject(subject=subject, strict=False)
            print(f"   - {subject}:")
            print(f"     • Model: {resolved['model']}")
            print(f"     • Subject Model: {resolved.get('subject_model')}")
            print(f"     • Used Subject Model: {resolved.get('used_subject_model')}")
            if resolved.get('warning'):
                print(f"     • Warning: {resolved['warning']}")
        except Exception as e:
            print(f"   - {subject}: Error - {e}")

    # Test chat
    print(f"\n5. Testing Chat Completion:")
    try:
        messages = [
            {"role": "system", "content": "你是一个化学学习助手。"},
            {"role": "user", "content": "什么是氧化还原反应？"}
        ]
        response = await svc.chat(
            messages=messages,
            model="wzm-sft-chemistry",
            temperature=0.7,
            max_tokens=100,
            trace_id="test"
        )
        print(f"   ✓ Chat successful!")
        print(f"   Response preview: {response[:200]}...")
    except Exception as e:
        print(f"   ✗ Chat failed: {e}")
        return 1

    print(f"\n{'=' * 60}")
    print("✓ All tests passed!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
