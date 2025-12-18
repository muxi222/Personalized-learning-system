-- 为image_files表添加original_image_id字段
-- 用于关联批改后的图片到原始图片

-- SQLite 不支持 IF NOT EXISTS for ALTER TABLE ADD COLUMN
-- 需要先检查字段是否存在，如果不存在则添加

-- 添加original_image_id字段
ALTER TABLE image_files ADD COLUMN original_image_id INTEGER;

-- 创建索引
CREATE INDEX IF NOT EXISTS ix_image_files_original_image_id ON image_files(original_image_id);

-- 注意：如果字段已存在，上面的 ALTER TABLE 会失败
-- 可以手动检查：PRAGMA table_info(image_files);
-- 或者使用 Python 脚本执行迁移

