-- Initialize database schema
-- NOTE (2026-01): This project primarily uses SQLite in docker-compose.
-- This SQL is kept as a convenient "single-shot" schema initializer and is written
-- to be SQLite-friendly (INTEGER PRIMARY KEY rowid alias) to avoid NULL PK issues.
-- 索引创建紧跟在表定义之后，方便集中查看和管理

-- Create database if not exists (handled by docker)
-- CREATE DATABASE learning_assistant;

-- ============================================================================
-- Users Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    grade VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Users indexes (already created by UNIQUE constraints on username and email)

-- ============================================================================
-- Image Files Table (图片文件去重表)
-- This table is needed by exam_corrections, so it must be created first
-- ============================================================================
CREATE TABLE IF NOT EXISTS image_files (
    id INTEGER PRIMARY KEY,
    file_hash VARCHAR(64) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    file_type VARCHAR(20) NOT NULL,
    image_type VARCHAR(20) DEFAULT 'original',
    subject VARCHAR(20),
    original_image_id INTEGER REFERENCES image_files(id),
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(50),
    reference_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Image Files indexes
CREATE INDEX IF NOT EXISTS idx_image_files_file_hash ON image_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_image_files_user_id ON image_files(user_id);
CREATE INDEX IF NOT EXISTS idx_image_files_file_type ON image_files(file_type);
CREATE INDEX IF NOT EXISTS idx_image_files_image_type ON image_files(image_type);
CREATE INDEX IF NOT EXISTS idx_image_files_subject ON image_files(subject);
CREATE INDEX IF NOT EXISTS idx_image_files_original_image_id ON image_files(original_image_id);

-- ============================================================================
-- Exam Corrections Table (AI批注记录表)
-- This table is needed by questions, so it must be created after image_files
-- ============================================================================
CREATE TABLE IF NOT EXISTS exam_corrections (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    -- NOTE: app stores Enum NAMEs (e.g. HISTORY) rather than Enum values (e.g. history)
    subject VARCHAR(20) DEFAULT 'OTHER',
    grade VARCHAR(20),
    exam_title VARCHAR(255),
    original_image_id INTEGER NOT NULL REFERENCES image_files(id),
    corrected_image_id INTEGER REFERENCES image_files(id),
    total_score FLOAT DEFAULT 0.0,
    max_score FLOAT DEFAULT 100.0,
    accuracy_rate FLOAT DEFAULT 0.0,
    question_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    wrong_count INTEGER DEFAULT 0,
    overall_analysis TEXT,
    weak_points JSON DEFAULT '[]',
    improvement_suggestions JSON DEFAULT '[]',
    questions_detail JSON DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Exam Corrections indexes
CREATE INDEX IF NOT EXISTS idx_exam_corrections_user_id ON exam_corrections(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_corrections_subject ON exam_corrections(subject);
CREATE INDEX IF NOT EXISTS idx_exam_corrections_grade ON exam_corrections(grade);
CREATE INDEX IF NOT EXISTS idx_exam_corrections_created_at ON exam_corrections(created_at);
CREATE INDEX IF NOT EXISTS idx_exam_corrections_original_image_id ON exam_corrections(original_image_id);
CREATE INDEX IF NOT EXISTS idx_exam_corrections_corrected_image_id ON exam_corrections(corrected_image_id);

-- ============================================================================
-- Questions Table (错题表)
-- ============================================================================
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    exam_correction_id INTEGER REFERENCES exam_corrections(id),
    title VARCHAR(255),
    content TEXT NOT NULL,
    image_urls JSON DEFAULT '[]',
    source_image_id INTEGER REFERENCES image_files(id),
    -- NOTE: app stores Enum NAMEs (e.g. HISTORY) rather than Enum values (e.g. history)
    subject VARCHAR(20) DEFAULT 'OTHER',
    grade VARCHAR(20),
    difficulty VARCHAR(20) DEFAULT 'MEDIUM',
    options JSON DEFAULT '[]',
    student_answer TEXT,
    correct_answer TEXT,
    explanation TEXT,
    is_correct BOOLEAN,
    score FLOAT,
    max_score FLOAT,
    knowledge_points JSON DEFAULT '[]',
    error_analysis TEXT,
    suggested_questions JSON DEFAULT '[]',
    source VARCHAR(100) DEFAULT 'MANUAL',
    source_description VARCHAR(100),
    chapter VARCHAR(100),
    tags JSON DEFAULT '[]',
    original_input TEXT,
    summarized_input TEXT,
    upload_group_id VARCHAR(64),
    upload_index INTEGER,
    review_count INTEGER DEFAULT 0,
    mastery_level FLOAT DEFAULT 0.0,
    next_review_at TIMESTAMP,
    last_reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Questions indexes
CREATE INDEX IF NOT EXISTS idx_questions_user_id ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS idx_questions_grade ON questions(grade);
CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at);
CREATE INDEX IF NOT EXISTS idx_questions_exam_correction_id ON questions(exam_correction_id);
CREATE INDEX IF NOT EXISTS idx_questions_upload_group_id ON questions(upload_group_id);
CREATE INDEX IF NOT EXISTS idx_questions_source_image_id ON questions(source_image_id);
CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source);

-- ============================================================================
-- Agent Tasks Table (任务表)
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY,
    task_id VARCHAR(36) UNIQUE NOT NULL,
    question_id INTEGER REFERENCES questions(id),
    -- NOTE: app stores Enum NAMEs (e.g. PENDING/COMPLETED) rather than Enum values (e.g. pending/completed)
    status VARCHAR(20) DEFAULT 'PENDING',
    progress FLOAT DEFAULT 0.0,
    current_step VARCHAR(100),
    result JSON,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Agent Tasks indexes
CREATE INDEX IF NOT EXISTS idx_agent_tasks_task_id ON agent_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created_at ON agent_tasks(created_at);

-- ============================================================================
-- Feedbacks Table (反馈表)
-- ============================================================================
CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    feedback_type VARCHAR(50) NOT NULL,
    rating INTEGER,
    comment TEXT,
    original_response TEXT,
    preferred_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Feedbacks indexes
CREATE INDEX IF NOT EXISTS idx_feedbacks_user_id ON feedbacks(user_id);
CREATE INDEX IF NOT EXISTS idx_feedbacks_question_id ON feedbacks(question_id);

-- ============================================================================
-- Knowledge Points Table (知识点表)
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_points (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    subject VARCHAR(20) NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES knowledge_points(id),
    level INTEGER DEFAULT 1,
    difficulty_avg FLOAT DEFAULT 0.5,
    importance FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Knowledge Points indexes
CREATE INDEX IF NOT EXISTS idx_knowledge_points_subject ON knowledge_points(subject);

-- ============================================================================
-- Default Data
-- ============================================================================
-- Insert default user for development
INSERT INTO users (username, email, hashed_password, full_name, grade)
VALUES ('demo', 'demo@example.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.FZcCOYz6TtxMQJqhN', 'Demo User', '高三')
ON CONFLICT (username) DO NOTHING;
