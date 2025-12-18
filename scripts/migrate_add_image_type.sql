-- 为image_files表添加image_type字段
-- 如果字段已存在，此操作会失败，但可以使用 IF NOT EXISTS 检查（SQLite不支持）

-- SQLite 不支持 IF NOT EXISTS for ALTER TABLE ADD COLUMN
-- 需要先检查字段是否存在，如果不存在则添加

-- 方法1: 直接添加（如果字段不存在会报错，但可以忽略）
ALTER TABLE image_files ADD COLUMN image_type VARCHAR(20) DEFAULT 'original';

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_image_files_image_type ON image_files(image_type);

-- 注意：如果字段已存在，上面的 ALTER TABLE 会失败
-- 可以手动检查：PRAGMA table_info(image_files);
-- 或者使用 Python 脚本执行迁移

