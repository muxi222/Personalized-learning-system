"""
Hybrid Search Service - FAISS + BM25
混合检索服务 - 结合向量检索和关键词检索

参考实现:
- Facebook FAISS: https://github.com/facebookresearch/faiss
- Rank-BM25: https://github.com/dorianbrown/rank_bm25
- Google Research Dual Encoder: Similar to ColBERT approach

混合检索策略:
1. FAISS 向量检索 (语义相似度)
2. BM25 关键词检索 (精确匹配)
3. 合并去重
4. 相似度过滤 (threshold = 0.55)
"""

import os
import json
import pickle
import logging
from typing import List, Optional, Dict, Any, Tuple
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果数据类"""
    doc_id: str
    score: float
    source: str  # 'faiss', 'bm25', 'hybrid'
    metadata: Dict[str, Any] = field(default_factory=dict)
    document: str = ""


@dataclass
class DocumentStore:
    """文档存储 - 用于存储原始文档和元数据"""
    doc_id: str
    content: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None


class HybridSearchService:
    """
    混合检索服务

    支持:
    - FAISS 向量检索 (语义相似度, cosine similarity)
    - BM25 关键词检索 (TF-IDF based)
    - 混合检索 (加权融合 + 去重 + 阈值过滤)

    特点:
    - 支持持久化存储 (用于Docker部署)
    - 支持增量更新
    - 支持多用户隔离
    """

    def __init__(self):
        self._faiss_index = None
        self._bm25_index = None
        self._document_store: Dict[str, DocumentStore] = {}
        self._id_to_idx: Dict[str, int] = {}  # doc_id -> FAISS index
        self._idx_to_id: Dict[int, str] = {}  # FAISS index -> doc_id
        self._tokenized_corpus: List[List[str]] = []
        self._initialized = False
        self._dimension = settings.EMBEDDING_DIMENSION

    async def initialize(self) -> bool:
        """初始化混合检索服务"""
        if self._initialized:
            return True

        try:
            import faiss
            from rank_bm25 import BM25Okapi

            # 确保目录存在
            Path(settings.VECTOR_STORE_PATH).mkdir(parents=True, exist_ok=True)
            Path(settings.BM25_INDEX_PATH).mkdir(parents=True, exist_ok=True)

            # 尝试加载已有索引
            if self._load_indices():
                logger.info("Loaded existing FAISS and BM25 indices")
            else:
                # 创建新索引
                self._faiss_index = faiss.IndexFlatIP(self._dimension)  # Inner Product (cosine similarity for normalized vectors)
                self._bm25_index = None  # Will be created when documents are added
                logger.info(f"Created new FAISS index with dimension {self._dimension}")

            self._initialized = True
            return True

        except ImportError as e:
            logger.error(f"Missing dependency: {e}. Install with: pip install faiss-cpu rank-bm25")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize hybrid search: {e}")
            return False

    def _load_indices(self) -> bool:
        """从磁盘加载索引"""
        try:
            import faiss

            faiss_path = Path(settings.VECTOR_STORE_PATH) / "index.faiss"
            bm25_path = Path(settings.BM25_INDEX_PATH) / "bm25.pkl"
            store_path = Path(settings.VECTOR_STORE_PATH) / "store.json"
            mapping_path = Path(settings.VECTOR_STORE_PATH) / "mapping.json"

            if not all(p.exists() for p in [faiss_path, store_path, mapping_path]):
                return False

            # 加载 FAISS 索引
            self._faiss_index = faiss.read_index(str(faiss_path))

            # 加载 BM25 索引 (如果存在)
            if bm25_path.exists():
                with open(bm25_path, 'rb') as f:
                    data = pickle.load(f)
                    self._bm25_index = data.get('index')
                    self._tokenized_corpus = data.get('corpus', [])

            # 加载文档存储
            with open(store_path, 'r', encoding='utf-8') as f:
                store_data = json.load(f)
                self._document_store = {
                    k: DocumentStore(**v) for k, v in store_data.items()
                }

            # 加载映射关系
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
                self._id_to_idx = mapping.get('id_to_idx', {})
                self._idx_to_id = {int(k): v for k, v in mapping.get('idx_to_id', {}).items()}

            return True

        except Exception as e:
            logger.warning(f"Failed to load indices: {e}")
            return False

    async def save_indices(self) -> bool:
        """持久化索引到磁盘"""
        try:
            import faiss

            faiss_path = Path(settings.VECTOR_STORE_PATH) / "index.faiss"
            bm25_path = Path(settings.BM25_INDEX_PATH) / "bm25.pkl"
            store_path = Path(settings.VECTOR_STORE_PATH) / "store.json"
            mapping_path = Path(settings.VECTOR_STORE_PATH) / "mapping.json"

            # 保存 FAISS 索引
            if self._faiss_index is not None:
                faiss.write_index(self._faiss_index, str(faiss_path))

            # 保存 BM25 索引
            if self._bm25_index is not None:
                with open(bm25_path, 'wb') as f:
                    pickle.dump({
                        'index': self._bm25_index,
                        'corpus': self._tokenized_corpus
                    }, f)

            # 保存文档存储
            store_data = {
                k: {
                    'doc_id': v.doc_id,
                    'content': v.content,
                    'metadata': v.metadata,
                }
                for k, v in self._document_store.items()
            }
            with open(store_path, 'w', encoding='utf-8') as f:
                json.dump(store_data, f, ensure_ascii=False, indent=2)

            # 保存映射关系
            with open(mapping_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'id_to_idx': self._id_to_idx,
                    'idx_to_id': {str(k): v for k, v in self._idx_to_id.items()}
                }, f)

            logger.info("Saved indices to disk")
            return True

        except Exception as e:
            logger.error(f"Failed to save indices: {e}")
            return False

    def _tokenize(self, text: str) -> List[str]:
        """
        文本分词 - 支持中英文混合
        使用简单的字符级分词 + 英文单词分词
        """
        import re

        # 中文按字符分，英文按单词分
        tokens = []

        # 分离中文和英文
        segments = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text.lower())

        for seg in segments:
            if re.match(r'[\u4e00-\u9fff]', seg):
                # 中文按字符分词
                tokens.extend(list(seg))
            else:
                # 英文保持单词
                tokens.append(seg)

        return tokens

    def _rebuild_bm25_index(self):
        """重建 BM25 索引"""
        from rank_bm25 import BM25Okapi

        if not self._tokenized_corpus:
            self._bm25_index = None
            return

        self._bm25_index = BM25Okapi(self._tokenized_corpus)

    async def add_document(
        self,
        doc_id: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        添加文档到索引

        Args:
            doc_id: 文档唯一ID
            content: 文档内容 (用于BM25检索)
            embedding: 文档向量 (用于FAISS检索)
            metadata: 元数据 (用户ID、学科、难度等)
        """
        if not self._initialized:
            await self.initialize()

        try:
            metadata = metadata or {}

            # 检查是否已存在，如果存在则更新
            if doc_id in self._document_store:
                await self.delete_document(doc_id)

            # 归一化向量 (用于余弦相似度)
            embedding_np = np.array(embedding, dtype=np.float32)
            embedding_np = embedding_np / np.linalg.norm(embedding_np)

            # 添加到 FAISS
            idx = self._faiss_index.ntotal
            self._faiss_index.add(embedding_np.reshape(1, -1))
            self._id_to_idx[doc_id] = idx
            self._idx_to_id[idx] = doc_id

            # 添加到 BM25
            tokens = self._tokenize(content)
            self._tokenized_corpus.append(tokens)
            self._rebuild_bm25_index()

            # 存储文档
            self._document_store[doc_id] = DocumentStore(
                doc_id=doc_id,
                content=content,
                metadata=metadata,
                embedding=embedding,
            )

            logger.debug(f"Added document {doc_id} to hybrid index")
            return True

        except Exception as e:
            logger.error(f"Failed to add document: {e}")
            return False

    async def delete_document(self, doc_id: str) -> bool:
        """
        从索引中删除文档
        注意: FAISS 不支持高效的单个删除，这里通过标记实现
        """
        if doc_id not in self._document_store:
            return True

        try:
            # 从文档存储中删除
            del self._document_store[doc_id]

            # 重建索引 (对于小规模数据集这是可行的)
            await self._rebuild_indices()

            logger.debug(f"Deleted document {doc_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            return False

    async def _rebuild_indices(self):
        """重建所有索引"""
        import faiss
        from ..services.embedding_service import get_embedding_service

        # 清空现有索引
        self._faiss_index = faiss.IndexFlatIP(self._dimension)
        self._id_to_idx = {}
        self._idx_to_id = {}
        self._tokenized_corpus = []

        # 重新添加所有文档
        for doc_id, doc in self._document_store.items():
            if doc.embedding:
                embedding_np = np.array(doc.embedding, dtype=np.float32)
                embedding_np = embedding_np / np.linalg.norm(embedding_np)

                idx = self._faiss_index.ntotal
                self._faiss_index.add(embedding_np.reshape(1, -1))
                self._id_to_idx[doc_id] = idx
                self._idx_to_id[idx] = doc_id

            tokens = self._tokenize(doc.content)
            self._tokenized_corpus.append(tokens)

        self._rebuild_bm25_index()

    async def search_vector(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        FAISS 向量检索
        """
        if not self._initialized:
            await self.initialize()

        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            return []

        try:
            # 归一化查询向量
            query_np = np.array(query_embedding, dtype=np.float32)
            query_np = query_np / np.linalg.norm(query_np)

            # 搜索
            scores, indices = self._faiss_index.search(query_np.reshape(1, -1), min(top_k, self._faiss_index.ntotal))

            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue

                doc_id = self._idx_to_id.get(idx)
                if not doc_id or doc_id not in self._document_store:
                    continue

                doc = self._document_store[doc_id]

                # 元数据过滤
                if filter_metadata:
                    if not self._match_metadata(doc.metadata, filter_metadata):
                        continue

                results.append(SearchResult(
                    doc_id=doc_id,
                    score=float(score),
                    source='faiss',
                    metadata=doc.metadata,
                    document=doc.content,
                ))

            return results

        except Exception as e:
            logger.error(f"FAISS search error: {e}")
            return []

    async def search_bm25(
        self,
        query_text: str,
        top_k: int = 10,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        BM25 关键词检索
        """
        if not self._initialized:
            await self.initialize()

        if self._bm25_index is None:
            return []

        try:
            # 分词
            query_tokens = self._tokenize(query_text)

            # BM25 检索
            scores = self._bm25_index.get_scores(query_tokens)

            # 获取 top-k
            top_indices = np.argsort(scores)[::-1][:top_k]

            results = []
            doc_ids = list(self._document_store.keys())

            for idx in top_indices:
                if idx >= len(doc_ids):
                    continue

                doc_id = doc_ids[idx]
                doc = self._document_store[doc_id]
                score = scores[idx]

                if score <= 0:
                    continue

                # 归一化 BM25 分数到 [0, 1]
                normalized_score = min(score / 10.0, 1.0)

                # 元数据过滤
                if filter_metadata:
                    if not self._match_metadata(doc.metadata, filter_metadata):
                        continue

                results.append(SearchResult(
                    doc_id=doc_id,
                    score=normalized_score,
                    source='bm25',
                    metadata=doc.metadata,
                    document=doc.content,
                ))

            return results

        except Exception as e:
            logger.error(f"BM25 search error: {e}")
            return []

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: List[float],
        top_k: int = 10,
        vector_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        similarity_threshold: Optional[float] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """
        混合检索 - FAISS + BM25

        策略:
        1. FAISS 向量检索 (语义相似度)
        2. BM25 关键词检索 (精确匹配)
        3. 加权融合
        4. 合并去重
        5. 相似度过滤 (threshold)

        Args:
            query_text: 查询文本
            query_embedding: 查询向量
            top_k: 返回数量
            vector_weight: FAISS 权重 (默认 0.6)
            bm25_weight: BM25 权重 (默认 0.4)
            similarity_threshold: 相似度阈值 (默认 0.55)
            filter_metadata: 元数据过滤条件
        """
        vector_weight = vector_weight or settings.HYBRID_SEARCH_VECTOR_WEIGHT
        bm25_weight = bm25_weight or settings.HYBRID_SEARCH_BM25_WEIGHT
        similarity_threshold = similarity_threshold or settings.HYBRID_SEARCH_SIMILARITY_THRESHOLD
        retrieve_k = settings.HYBRID_SEARCH_TOP_K

        # 1. FAISS 向量检索
        faiss_results = await self.search_vector(
            query_embedding=query_embedding,
            top_k=retrieve_k,
            filter_metadata=filter_metadata,
        )

        # 2. BM25 关键词检索
        bm25_results = await self.search_bm25(
            query_text=query_text,
            top_k=retrieve_k,
            filter_metadata=filter_metadata,
        )

        # 3. 加权融合 + 合并去重
        score_map: Dict[str, Tuple[float, SearchResult]] = {}

        for result in faiss_results:
            weighted_score = result.score * vector_weight
            score_map[result.doc_id] = (weighted_score, result)

        for result in bm25_results:
            weighted_score = result.score * bm25_weight
            if result.doc_id in score_map:
                # 合并分数
                existing_score, existing_result = score_map[result.doc_id]
                combined_score = existing_score + weighted_score
                score_map[result.doc_id] = (combined_score, SearchResult(
                    doc_id=result.doc_id,
                    score=combined_score,
                    source='hybrid',
                    metadata=existing_result.metadata,
                    document=existing_result.document,
                ))
            else:
                score_map[result.doc_id] = (weighted_score, result)

        # 4. 按分数排序
        sorted_results = sorted(
            score_map.values(),
            key=lambda x: x[0],
            reverse=True
        )

        # 5. 相似度过滤
        filtered_results = [
            result for score, result in sorted_results
            if score >= similarity_threshold
        ]

        return filtered_results[:top_k]

    def _match_metadata(
        self,
        metadata: Dict[str, Any],
        filter_conditions: Dict[str, Any]
    ) -> bool:
        """检查元数据是否匹配过滤条件"""
        for key, value in filter_conditions.items():
            if key not in metadata:
                return False
            if isinstance(value, list):
                if metadata[key] not in value:
                    return False
            elif metadata[key] != value:
                return False
        return True

    @property
    def count(self) -> int:
        """获取文档总数"""
        return len(self._document_store)

    async def get_document(self, doc_id: str) -> Optional[DocumentStore]:
        """获取单个文档"""
        return self._document_store.get(doc_id)

    async def get_user_documents(
        self,
        user_id: int,
        doc_type: Optional[str] = None,
    ) -> List[DocumentStore]:
        """
        获取用户的所有文档

        Args:
            user_id: 用户ID
            doc_type: 文档类型 (question, note, correction_record)
        """
        results = []
        for doc in self._document_store.values():
            if doc.metadata.get('user_id') == user_id:
                if doc_type and doc.metadata.get('doc_type') != doc_type:
                    continue
                results.append(doc)
        return results


# Singleton instance
_hybrid_search_service: Optional[HybridSearchService] = None


@lru_cache()
def get_hybrid_search_service() -> HybridSearchService:
    """Get singleton hybrid search service instance"""
    global _hybrid_search_service
    if _hybrid_search_service is None:
        _hybrid_search_service = HybridSearchService()
    return _hybrid_search_service
