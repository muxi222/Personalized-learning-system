"""
Database Session Management
支持 PostgreSQL (生产) 和 SQLite (开发)
"""

import os
from typing import AsyncGenerator

import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool
from sqlalchemy import text

from ..base_config import get_base_settings

settings = get_base_settings()
logger = logging.getLogger(__name__)

# Create Base class for declarative models
Base = declarative_base()

def _create_engine() -> AsyncEngine:
    """Create async database engine based on configuration"""
    database_url = settings.DATABASE_URL

    # SQLite specific configuration
    if "sqlite" in database_url:
        # Ensure directory exists
        db_path = database_url.split("///")[-1]
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        return create_async_engine(
            database_url,
            echo=settings.DATABASE_ECHO,
            connect_args={
                "check_same_thread": False,
                "timeout": 30.0,  # 增加超时时间到30秒，避免并发访问时的数据库锁定错误
            },
            poolclass=StaticPool,
        )

    # PostgreSQL configuration
    return create_async_engine(
        database_url,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
    )

# Create engine instance
engine = _create_engine()

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database session.
    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def init_db() -> None:
    """Initialize database tables"""
    async with engine.begin() as conn:
        # Import all models to ensure they are registered with Base
        from ..db import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)

        # Lightweight SQLite migrations (dev only): add new columns if missing.
        # We avoid Alembic here to keep the teaching project simple.
        if "sqlite" in settings.DATABASE_URL:
            await _sqlite_ensure_image_files_pk(conn)
            await _sqlite_ensure_exam_corrections_pk(conn)
            await _sqlite_ensure_questions_pk(conn)
            await _sqlite_ensure_question_order_columns(conn)
            await _sqlite_ensure_question_image_and_correctness_columns(conn)
            await _sqlite_ensure_question_legacy_columns(conn)
            await _sqlite_ensure_agent_tasks_pk(conn)


async def _sqlite_ensure_question_order_columns(conn) -> None:
    """
    SQLite only: ensure questions.upload_group_id / questions.upload_index exist.
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(questions)"))).fetchall()
        existing = {r[1] for r in rows}  # (cid, name, type, notnull, dflt_value, pk)
        if "upload_group_id" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.upload_group_id")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN upload_group_id VARCHAR(64)"))
        if "upload_index" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.upload_index")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN upload_index INTEGER"))
    except Exception:
        # Best-effort: do not block app startup if migration fails
        logger.exception("[sqlite_migrate] ensure questions.upload_group_id/upload_index failed")
        return


async def _sqlite_ensure_question_image_and_correctness_columns(conn) -> None:
    """
    SQLite only: ensure new question columns exist (best-effort).
    - questions.source_image_id
    - questions.is_correct
    - questions.score
    - questions.max_score
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(questions)"))).fetchall()
        existing = {r[1] for r in rows}
        if "source_image_id" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.source_image_id")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN source_image_id INTEGER"))
        if "is_correct" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.is_correct")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN is_correct BOOLEAN"))
        if "score" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.score")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN score FLOAT"))
        if "max_score" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.max_score")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN max_score FLOAT"))
    except Exception:
        logger.exception("[sqlite_migrate] ensure questions.source_image_id/is_correct/score/max_score failed")
        return


async def _sqlite_ensure_question_legacy_columns(conn) -> None:
    """
    SQLite only: ensure legacy columns exist for older sqlite DB files.
    This prevents runtime errors like: "no such column: questions.grade".

    Columns are derived from current ORM model fields commonly selected by queries:
    - questions.grade
    - questions.options
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(questions)"))).fetchall()
        existing = {r[1] for r in rows}
        if "grade" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.grade")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN grade VARCHAR(20)"))
        if "options" not in existing:
            logger.warning("[sqlite_migrate] adding column questions.options")
            await conn.execute(text("ALTER TABLE questions ADD COLUMN options JSON"))
    except Exception:
        logger.exception("[sqlite_migrate] ensure questions.grade/options failed")
        return


async def _sqlite_ensure_agent_tasks_pk(conn) -> None:
    """
    SQLite only: ensure agent_tasks has a working INTEGER PRIMARY KEY 'id'.
    Some legacy sqlite DBs created agent_tasks without a real PK, which breaks
    ORM refresh() and may cause: "Could not refresh instance '<AgentTask ...>'".
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(agent_tasks)"))).fetchall()
        if not rows:
            return
        # rows: (cid, name, type, notnull, dflt_value, pk)
        info = {r[1]: {"type": (r[2] or ""), "pk": r[5]} for r in rows}
        id_info = info.get("id", {})
        id_pk_ok = id_info.get("pk") == 1
        id_type_ok = "int" in str(id_info.get("type") or "").lower()
        # Must be INTEGER PRIMARY KEY (rowid alias) for reliable ORM identity/refresh behavior.
        if id_pk_ok and id_type_ok:
            return

        # Rebuild table with correct schema
        logger.warning("[sqlite_migrate] rebuilding table agent_tasks to ensure INTEGER PRIMARY KEY id")
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(
            text(
                """
CREATE TABLE IF NOT EXISTS agent_tasks_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id VARCHAR(36) UNIQUE NOT NULL,
  question_id INTEGER,
  status VARCHAR(20) DEFAULT 'pending',
  progress FLOAT DEFAULT 0.0,
  current_step VARCHAR(100),
  result JSON,
  error_message TEXT,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  created_at TIMESTAMP
)
"""
            )
        )

        desired_cols = [
            "task_id",
            "question_id",
            "status",
            "progress",
            "current_step",
            "result",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        ]
        existing_cols = [c for c in desired_cols if c in info]
        if existing_cols:
            cols_csv = ", ".join(existing_cols)
            await conn.execute(
                text(
                    f"INSERT INTO agent_tasks_new ({cols_csv}) SELECT {cols_csv} FROM agent_tasks"
                )
            )

        await conn.execute(text("DROP TABLE agent_tasks"))
        await conn.execute(text("ALTER TABLE agent_tasks_new RENAME TO agent_tasks"))

        # Recreate indexes (best-effort)
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_tasks_task_id ON agent_tasks(task_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status)"))

        await conn.execute(text("PRAGMA foreign_keys=ON"))
    except Exception:
        # Best-effort: do not block app startup
        logger.exception("[sqlite_migrate] rebuild agent_tasks failed")
        try:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        except Exception:
            pass
        return


async def _sqlite_ensure_image_files_pk(conn) -> None:
    """
    SQLite only: ensure image_files has a working INTEGER PRIMARY KEY 'id'.
    Some legacy sqlite DBs created image_files without a real PK, which breaks
    ORM refresh() and may cause: "Could not refresh instance '<ImageFile ...>'".
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(image_files)"))).fetchall()
        if not rows:
            return
        info = {r[1]: {"type": (r[2] or ""), "pk": r[5]} for r in rows}
        id_info = info.get("id", {})
        id_pk_ok = id_info.get("pk") == 1
        id_type_ok = "int" in str(id_info.get("type") or "").lower()
        # Must be INTEGER PRIMARY KEY (rowid alias). Legacy schemas may have "SERIAL PRIMARY KEY",
        # which is NOT a rowid alias in SQLite and breaks ORM refresh/identity.
        if id_pk_ok and id_type_ok:
            return

        # Critical: preserve existing ids to avoid breaking references
        logger.warning("[sqlite_migrate] rebuilding table image_files to ensure INTEGER PRIMARY KEY id (preserving existing ids)")
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(
            text(
                """
CREATE TABLE IF NOT EXISTS image_files_new (
  id INTEGER PRIMARY KEY,
  file_hash VARCHAR(64) UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  file_type VARCHAR(20) NOT NULL,
  image_type VARCHAR(20) DEFAULT 'original',
  subject VARCHAR(20),
  original_image_id INTEGER,
  file_path VARCHAR(500) NOT NULL,
  file_size INTEGER NOT NULL,
  mime_type VARCHAR(50),
  reference_count INTEGER DEFAULT 1,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
"""
            )
        )

        desired_cols = [
            "id",
            "file_hash",
            "user_id",
            "file_type",
            "image_type",
            "subject",
            "original_image_id",
            "file_path",
            "file_size",
            "mime_type",
            "reference_count",
            "created_at",
            "updated_at",
        ]
        existing_cols = [c for c in desired_cols if c in info]
        if existing_cols:
            cols_csv = ", ".join(existing_cols)
            await conn.execute(text(f"INSERT INTO image_files_new ({cols_csv}) SELECT {cols_csv} FROM image_files"))

        await conn.execute(text("DROP TABLE image_files"))
        await conn.execute(text("ALTER TABLE image_files_new RENAME TO image_files"))

        # Recreate indexes (best-effort)
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_image_files_file_hash ON image_files(file_hash)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_image_files_user_id ON image_files(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_image_files_file_type ON image_files(file_type)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_image_files_image_type ON image_files(image_type)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_image_files_subject ON image_files(subject)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_image_files_original_image_id ON image_files(original_image_id)"))

        await conn.execute(text("PRAGMA foreign_keys=ON"))
    except Exception:
        logger.exception("[sqlite_migrate] rebuild image_files failed")
        try:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        except Exception:
            pass
        return


async def _sqlite_ensure_questions_pk(conn) -> None:
    """
    SQLite only: ensure questions has a working INTEGER PRIMARY KEY 'id' (rowid alias).
    Without this, ORM identity/refresh may fail (e.g., "Could not refresh instance '<Question ...>'").
    Preserves existing ids to avoid breaking references (agent_tasks.question_id, etc.).
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(questions)"))).fetchall()
        if not rows:
            return
        info = {r[1]: {"type": (r[2] or ""), "pk": r[5]} for r in rows}
        id_info = info.get("id", {})
        id_pk_ok = id_info.get("pk") == 1
        id_type_ok = "int" in str(id_info.get("type") or "").lower()
        if id_pk_ok and id_type_ok:
            return

        logger.warning("[sqlite_migrate] rebuilding table questions to ensure INTEGER PRIMARY KEY id (preserving existing ids)")
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Keep a subset of constraints; we mainly need correct PK and columns used by the app.
        await conn.execute(
            text(
                """
CREATE TABLE IF NOT EXISTS questions_new (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  exam_correction_id INTEGER,
  title VARCHAR(255),
  content TEXT NOT NULL,
  image_urls JSON,
  source_image_id INTEGER,
  subject VARCHAR(20) DEFAULT 'other',
  grade VARCHAR(20),
  difficulty VARCHAR(20) DEFAULT 'medium',
  options JSON,
  student_answer TEXT,
  correct_answer TEXT,
  explanation TEXT,
  is_correct BOOLEAN,
  score FLOAT,
  max_score FLOAT,
  knowledge_points JSON,
  error_analysis TEXT,
  suggested_questions JSON,
  source VARCHAR(100),
  source_description VARCHAR(100),
  chapter VARCHAR(100),
  tags JSON,
  original_input TEXT,
  summarized_input TEXT,
  upload_group_id VARCHAR(64),
  upload_index INTEGER,
  review_count INTEGER,
  mastery_level FLOAT,
  next_review_at TIMESTAMP,
  last_reviewed_at TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
"""
            )
        )

        desired_cols = [
            "id",
            "user_id",
            "exam_correction_id",
            "title",
            "content",
            "image_urls",
            "source_image_id",
            "subject",
            "grade",
            "difficulty",
            "options",
            "student_answer",
            "correct_answer",
            "explanation",
            "is_correct",
            "score",
            "max_score",
            "knowledge_points",
            "error_analysis",
            "suggested_questions",
            "source",
            "source_description",
            "chapter",
            "tags",
            "original_input",
            "summarized_input",
            "upload_group_id",
            "upload_index",
            "review_count",
            "mastery_level",
            "next_review_at",
            "last_reviewed_at",
            "created_at",
            "updated_at",
        ]
        existing_cols = [c for c in desired_cols if c in info]
        if existing_cols:
            cols_csv = ", ".join(existing_cols)
            await conn.execute(text(f"INSERT INTO questions_new ({cols_csv}) SELECT {cols_csv} FROM questions"))

        await conn.execute(text("DROP TABLE questions"))
        await conn.execute(text("ALTER TABLE questions_new RENAME TO questions"))

        # Recreate key indexes used by queries (best-effort)
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_user_id ON questions(user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_upload_group_id ON questions(upload_group_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_questions_source_image_id ON questions(source_image_id)"))

        await conn.execute(text("PRAGMA foreign_keys=ON"))
    except Exception:
        logger.exception("[sqlite_migrate] rebuild questions failed")
        try:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        except Exception:
            pass
        return


async def _sqlite_ensure_exam_corrections_pk(conn) -> None:
    """
    SQLite only: ensure exam_corrections.id is a real INTEGER PRIMARY KEY (rowid alias).

    Legacy schemas may have "SERIAL PRIMARY KEY" which does NOT auto-populate in SQLite,
    leading to NULL ids. When primary key columns are NULL, SQLAlchemy may return None
    rows for ORM entities, breaking:
    - list corrections (500 due to None rows)
    - get correction images by correction_id (404 because id lookup can't find NULL id rows)
    """
    try:
        rows = (await conn.execute(text("PRAGMA table_info(exam_corrections)"))).fetchall()
        if not rows:
            return
        info = {r[1]: {"type": (r[2] or ""), "pk": r[5]} for r in rows}
        id_info = info.get("id", {})
        id_pk_ok = id_info.get("pk") == 1
        id_type_ok = "int" in str(id_info.get("type") or "").lower()
        if id_pk_ok and id_type_ok:
            return

        # Caller explicitly allows clearing legacy exam_corrections data; prefer the simplest rebuild:
        # drop the table and re-create from SQLAlchemy metadata (avoids duplicating schema+indexes here).
        logger.warning("[sqlite_migrate] rebuilding table exam_corrections to ensure INTEGER PRIMARY KEY id (dropping existing exam_corrections data)")
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        # Break references from questions to corrections (we are dropping corrections data)
        try:
            await conn.execute(text("UPDATE questions SET exam_correction_id = NULL WHERE exam_correction_id IS NOT NULL"))
        except Exception:
            # Best-effort: questions table may not exist yet in some bootstraps
            pass

        await conn.execute(text("DROP TABLE IF EXISTS exam_corrections"))

        # Recreate using ORM metadata (tables + column indexes)
        await conn.run_sync(Base.metadata.create_all)

        await conn.execute(text("PRAGMA foreign_keys=ON"))
    except Exception:
        logger.exception("[sqlite_migrate] rebuild exam_corrections failed")
        try:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        except Exception:
            pass
        return

async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()
