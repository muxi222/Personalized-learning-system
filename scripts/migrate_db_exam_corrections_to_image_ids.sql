-- 将exam_corrections表中的路径字段改为ID字段
-- 1. 添加新字段
ALTER TABLE exam_corrections ADD COLUMN original_image_id INTEGER;
ALTER TABLE exam_corrections ADD COLUMN corrected_image_id INTEGER;

-- 2. 创建索引
CREATE INDEX IF NOT EXISTS ix_exam_corrections_original_image_id ON exam_corrections(original_image_id);
CREATE INDEX IF NOT EXISTS ix_exam_corrections_corrected_image_id ON exam_corrections(corrected_image_id);

-- 3. 添加外键约束（可选，如果数据已经存在可能需要先迁移数据）
-- ALTER TABLE exam_corrections ADD CONSTRAINT fk_exam_corrections_original_image 
--     FOREIGN KEY (original_image_id) REFERENCES image_files(id);
-- ALTER TABLE exam_corrections ADD CONSTRAINT fk_exam_corrections_corrected_image 
--     FOREIGN KEY (corrected_image_id) REFERENCES image_files(id);

-- 4. 在image_files表中添加image_type字段（如果还没有）
-- 注意：SQLite不支持直接添加枚举类型，需要先添加字符串字段
ALTER TABLE image_files ADD COLUMN image_type VARCHAR(20) DEFAULT 'original';

-- 5. 创建索引
CREATE INDEX IF NOT EXISTS ix_image_files_image_type ON image_files(image_type);

-- 注意：旧数据迁移需要手动处理
-- 1. 根据original_image_path和corrected_image_path查找对应的image_files记录
-- 2. 更新exam_corrections表的original_image_id和corrected_image_id字段
-- 3. 删除旧的路径字段（可选，建议保留一段时间以便回滚）

