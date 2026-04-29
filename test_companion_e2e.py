#!/usr/bin/env python3
"""
End-to-end test for WZM companion chat API
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from backend.core.db.session import async_session_maker
from backend.core.db.models import User
from backend.modules.wzm.config import settings
import httpx
import jwt

def create_access_token(user_id: int) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

async def main():
    print("=" * 60)
    print("End-to-End Test: WZM Companion Chat API")
    print("=" * 60)

    # 1. Get or create test user
    async with async_session_maker() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()

        if not user:
            print("\n✗ No users found in database. Please create a user first.")
            print("  You can register via: POST http://127.0.0.1:6004/api/v1/users/register")
            return 1

        print(f"\n1. Test User:")
        print(f"   - ID: {user.id}")
        print(f"   - Username: {user.username}")
        print(f"   - Email: {user.email}")

    # 2. Create access token
    token = create_access_token(user.id)
    print(f"\n2. Access Token: {token[:50]}...")

    # 3. Test companion chat endpoint
    print(f"\n3. Testing Companion Chat API...")

    url = "http://127.0.0.1:6004/api/v1/companion/chat"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "message": "什么是氧化还原反应？",
        "mode": "chat"
    }
    params = {
        "subject": "chemistry"
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                print(f"   ✓ Request successful!")
                print(f"   - Conversation ID: {data.get('conversation_id')}")
                print(f"   - Retrieved items: {len(data.get('retrieved', []))}")
                print(f"   - Assistant message preview:")
                print(f"     {data.get('assistant_message', '')[:200]}...")
            else:
                print(f"   ✗ Request failed!")
                print(f"   - Status: {response.status_code}")
                print(f"   - Response: {response.text}")
                return 1
        except Exception as e:
            print(f"   ✗ Request error: {e}")
            return 1

    # 4. Test streaming endpoint
    print(f"\n4. Testing Companion Chat Stream API...")

    stream_url = "http://127.0.0.1:6004/api/v1/companion/chat/stream"

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", stream_url, json=payload, headers=headers, params=params) as response:
                if response.status_code == 200:
                    print(f"   ✓ Stream started!")
                    print(f"   - Receiving chunks...")

                    chunk_count = 0
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            chunk_count += 1
                            if chunk_count <= 3:
                                print(f"     Chunk {chunk_count}: {line[:80]}...")

                    print(f"   ✓ Stream completed! Total chunks: {chunk_count}")
                else:
                    print(f"   ✗ Stream failed!")
                    print(f"   - Status: {response.status_code}")
                    print(f"   - Response: {await response.aread()}")
                    return 1
        except Exception as e:
            print(f"   ✗ Stream error: {e}")
            return 1

    print(f"\n{'=' * 60}")
    print("✓ All end-to-end tests passed!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
