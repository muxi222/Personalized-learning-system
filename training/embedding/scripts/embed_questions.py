#!/usr/bin/env python3
"""
LEGACY script (deprecated).

Embedding/index building is now module-owned under:
  `training/modules/<module>/embedding/`

For Tony, use:
  `training/modules/tony/embedding/scripts/build_index.py`

Or the pipeline helper:
  `./deploy/scripts/pipeline.sh embed-index --module tony ...`
"""

raise SystemExit(
    "Deprecated: use training/modules/<module>/embedding/scripts/build_index.py "
    "(Tony implemented) or deploy/scripts/pipeline.sh embed-index --module tony"
)
    
    def _load_model(self, model_key: str) -> SentenceTransformer:
        """懒加载Embedding模型"""
        if model_key not in self.models:
            config = EMBEDDING_MODELS[model_key]
            logger.info(f"加载Embedding模型: {config['model_name']}")
            self.models[model_key] = SentenceTransformer(
                config["model_name"],
                device=self.device,
            )
        return self.models[model_key]
    
    def embed_text(self, text: str, subject: str = "") -> List[float]:
        """
        生成文本的Embedding向量
        
        根据设计文档4.1节:
        - 根据错题的subject（学科），选择对应的Embedding模型
        """
        model_key = self._get_model_key_for_subject(subject)
        model = self._load_model(model_key)
        
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    async def process_question(
        self,
        question_id: int,
        question_body: str,
        subject: str,
        knowledge_points: Optional[List[str]] = None,
    ) -> bool:
        """
        处理单个题目的Embedding
        
        Args:
            question_id: 题目ID
            question_body: 题目内容
            subject: 学科
            knowledge_points: 知识点列表
        """
        try:
            # 合并知识点以增强Embedding
            text = question_body
            if knowledge_points:
                text = f"{text}\n知识点: {', '.join(knowledge_points)}"
            
            # 生成Embedding
            embedding = self.embed_text(text, subject)
            
            # 存入向量数据库
            # TODO: 调用线上 FAISS + BM25 混合检索服务写入接口
            logger.info(
                f"✅ 处理完成: question_id={question_id}, "
                f"subject={subject}, dimension={len(embedding)}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 处理失败: question_id={question_id}, error={e}")
            return False


async def run_worker():
    """
    运行Embedding Worker
    
    在生产环境中，这个Worker会:
    1. 连接到消息队列 (如RabbitMQ, Redis)
    2. 持续监听待处理的Embedding任务
    3. 处理任务并将结果存入向量数据库
    """
    worker = EmbeddingWorker()
    logger.info("🚀 Embedding Worker 已启动")
    logger.info(f"📊 使用设备: {worker.device}")
    
    # 示例: 处理测试数据
    test_questions = [
        {
            "question_id": 1,
            "question_body": "已知函数f(x) = x³ - 3x + 1，求f(x)的极值点。",
            "subject": "数学",
            "knowledge_points": ["导数", "极值", "函数"],
        },
        {
            "question_id": 2,
            "question_body": "What is the past tense of 'go'?",
            "subject": "英语",
            "knowledge_points": ["动词时态", "不规则动词"],
        },
    ]
    
    for q in test_questions:
        await worker.process_question(
            question_id=q["question_id"],
            question_body=q["question_body"],
            subject=q["subject"],
            knowledge_points=q["knowledge_points"],
        )


def main():
    """入口函数"""
    print("=" * 50)
    print("🎓 学习小书童 - Embedding Worker")
    print("=" * 50)
    print()
    print("📋 支持的Embedding模型:")
    for key, config in EMBEDDING_MODELS.items():
        print(f"  - {key}: {config['model_name']}")
        if config['subjects']:
            print(f"    学科: {', '.join(config['subjects'])}")
    print()
    
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

