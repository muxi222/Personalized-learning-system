-- Initialize database schema
-- This script is used by docker-compose to initialize PostgreSQL

-- Create database if not exists (handled by docker)
-- CREATE DATABASE learning_assistant;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(100),
    grade VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create questions table
CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title VARCHAR(255),
    content TEXT NOT NULL,
    image_urls JSONB DEFAULT '[]',
    subject VARCHAR(20) DEFAULT 'other',
    difficulty VARCHAR(20) DEFAULT 'medium',
    student_answer TEXT,
    correct_answer TEXT,
    explanation TEXT,
    knowledge_points JSONB DEFAULT '[]',
    error_analysis TEXT,
    suggested_questions JSONB DEFAULT '[]',
    source VARCHAR(100),
    chapter VARCHAR(100),
    tags JSONB DEFAULT '[]',
    review_count INTEGER DEFAULT 0,
    mastery_level FLOAT DEFAULT 0.0,
    next_review_at TIMESTAMP,
    last_reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create agent_tasks table
CREATE TABLE IF NOT EXISTS agent_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) UNIQUE NOT NULL,
    question_id INTEGER REFERENCES questions(id),
    status VARCHAR(20) DEFAULT 'pending',
    progress FLOAT DEFAULT 0.0,
    current_step VARCHAR(100),
    result JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create feedbacks table
CREATE TABLE IF NOT EXISTS feedbacks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    feedback_type VARCHAR(50) NOT NULL,
    rating INTEGER,
    comment TEXT,
    original_response TEXT,
    preferred_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create knowledge_points table
CREATE TABLE IF NOT EXISTS knowledge_points (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    subject VARCHAR(20) NOT NULL,
    description TEXT,
    parent_id INTEGER REFERENCES knowledge_points(id),
    level INTEGER DEFAULT 1,
    difficulty_avg FLOAT DEFAULT 0.5,
    importance FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_questions_user_id ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_task_id ON agent_tasks(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_feedbacks_user_id ON feedbacks(user_id);
CREATE INDEX IF NOT EXISTS idx_feedbacks_question_id ON feedbacks(question_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_subject ON knowledge_points(subject);

-- Insert default user for development
INSERT INTO users (username, email, hashed_password, full_name, grade)
VALUES ('demo', 'demo@example.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.FZcCOYz6TtxMQJqhN', 'Demo User', '高三')
ON CONFLICT (username) DO NOTHING;

