#!/usr/bin/env python3
"""
数据库迁移脚本：为image_files表添加image_type字段
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, inspect
from backend.app.db.session import engine
from backend.app.core.config import settings


async def migrate():
    """执行迁移：添加image_type字段"""
    print("=" * 60)
    print("数据库迁移：添加image_type字段")
    print("=" * 60)
    
    try:
        async with engine.begin() as conn:
            # 检查字段是否已存在（SQLite）
            if "sqlite" in settings.DATABASE_URL:
                print("检测到SQLite数据库")
                # 获取表结构
                result = await conn.execute(text("PRAGMA table_info(image_files)"))
                columns = result.fetchall()
                column_names = [col[1] for col in columns]
                
                print(f"当前image_files表的字段: {', '.join(column_names)}")
                
                if "image_type" in column_names:
                    print("✓ image_type字段已存在，跳过迁移")
                    return
                
                print("添加image_type字段...")
                try:
                    await conn.execute(text("""
                        ALTER TABLE image_files 
                        ADD COLUMN image_type VARCHAR(20) DEFAULT 'original'
                    """))
                    print("✓ image_type字段添加成功")
                except Exception as e:
                    if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                        print("✓ image_type字段已存在（忽略错误）")
                    else:
                        print(f"✗ 添加字段失败: {e}")
                        raise
                
                # 创建索引
                print("创建image_type索引...")
                try:
                    await conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_image_files_image_type 
                        ON image_files(image_type)
                    """))
                    print("✓ image_type索引创建成功")
                except Exception as e:
                    print(f"⚠ 创建索引警告: {e}")
            
            # PostgreSQL
            else:
                print("检测到PostgreSQL数据库")
                try:
                    await conn.execute(text("""
                        ALTER TABLE image_files 
                        ADD COLUMN IF NOT EXISTS image_type VARCHAR(20) DEFAULT 'original'
                    """))
                    print("✓ image_type字段添加成功")
                except Exception as e:
                    print(f"✗ 添加字段失败: {e}")
                    raise
                
                try:
                    await conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_image_files_image_type 
                        ON image_files(image_type)
                    """))
                    print("✓ image_type索引创建成功")
                except Exception as e:
                    print(f"⚠ 创建索引警告: {e}")
        
        print("=" * 60)
        print("✓ 迁移完成！")
        print("=" * 60)
    
    except Exception as e:
        print("=" * 60)
        print(f"✗ 迁移失败: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(migrate())

