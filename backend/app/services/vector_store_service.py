"""
Vector Store Service
向量数据库服务 - 基于 FAISS + BM25 混合检索
"""

import logging
from typing import List, Optional, Dict, Any
from functools import lru_cache

from .hybrid_search_service import get_hybrid_search_service

logger = logging.getLogger(__name__)


class VectorStoreService:
    """
    向量数据库服务
    兼容旧的向量存储接口，内部统一使用 FAISS 混合检索服务
    """

    def __init__(self):
        self._hybrid_service = get_hybrid_search_service()
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize vector store connection"""
        if self._initialized:
            return True

        try:
            self._initialized = await self._hybrid_service.initialize()
            if self._initialized:
                logger.info("Vector store initialized via FAISS hybrid service")
            return self._initialized
        except ModuleNotFoundError as exc:
            if exc.name == "chromadb":
                logger.error(
                    "ChromaDB backend has been removed. Please update your environment "
                    "to use the built-in FAISS + BM25 hybrid service."
                )
                self._initialized = False
                return False
            logger.error(f"Missing dependency while initializing vector store: {exc}")
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            self._initialized = False
            return False

    async def add_embedding(
        self,
        doc_id: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        document: Optional[str] = None,
    ) -> bool:
        """
        Add a single embedding to the vector store
        
        Args:
            doc_id: Unique document ID (usually question_id)
            embedding: Embedding vector
            metadata: Optional metadata (subject, difficulty, etc.)
            document: Optional document text
        """
        if not await self._ensure_initialized():
            return False

        try:
            metadata = metadata or {}
            content = document or metadata.get("content", "")
            return await self._hybrid_service.add_document(
                doc_id=doc_id,
                content=content,
                embedding=embedding,
                metadata=metadata,
            )
        except Exception as e:
            logger.error(f"Failed to add embedding: {e}")
            return False

    async def add_embeddings_batch(
        self,
        doc_ids: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        documents: Optional[List[str]] = None,
    ) -> bool:
        """Add multiple embeddings in batch"""
        if not await self._ensure_initialized():
            return False

        try:
            metadatas = metadatas or [{}] * len(doc_ids)
            documents = documents or ["" for _ in doc_ids]

            for doc_id, embedding, metadata, document in zip(
                doc_ids, embeddings, metadatas, documents
            ):
                await self.add_embedding(
                    doc_id=doc_id,
                    embedding=embedding,
                    metadata=metadata,
                    document=document,
                )

            logger.debug(f"Added {len(doc_ids)} embeddings in batch")
            return True
        except Exception as e:
            logger.error(f"Failed to add embeddings batch: {e}")
            return False

    async def search_similar(
        self,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents by embedding
        
        Args:
            query_embedding: Query embedding vector
            n_results: Number of results to return
            where: Optional filter conditions
            include: Fields to include in results
            
        Returns:
            List of similar documents with scores
        """
        if not await self._ensure_initialized():
            return []

        include = include or ["metadatas", "distances", "documents"]

        try:
            search_results = await self._hybrid_service.search_vector(
                query_embedding=query_embedding,
                top_k=n_results,
                filter_metadata=where,
            )

            formatted = []
            for result in search_results:
                item = {"id": result.doc_id}
                if "distances" in include or "score" in include:
                    item["score"] = float(result.score)
                if "metadatas" in include:
                    item["metadata"] = result.metadata
                if "documents" in include:
                    item["document"] = result.document
                formatted.append(item)

            return formatted
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def search_by_text(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents by text
        Uses embedding service to convert text to embedding first
        """
        from .embedding_service import get_embedding_service

        embedding_service = get_embedding_service()
        query_embedding = await embedding_service.embed_text(query_text)

        if not query_embedding:
            logger.error("Failed to generate query embedding")
            return []

        return await self.search_similar(
            query_embedding=query_embedding,
            n_results=n_results,
            where=where,
        )

    async def delete_embedding(self, doc_id: str) -> bool:
        """Delete an embedding by document ID"""
        if not await self._ensure_initialized():
            return False

        try:
            return await self._hybrid_service.delete_document(doc_id)
        except Exception as e:
            logger.error(f"Failed to delete embedding: {e}")
            return False

    async def get_embedding(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get embedding and metadata by document ID"""
        if not await self._ensure_initialized():
            return None

        try:
            document = await self._hybrid_service.get_document(doc_id)
            if not document:
                return None
            return {
                "id": document.doc_id,
                "embedding": document.embedding,
                "metadata": document.metadata,
                "document": document.content,
            }
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            return None

    @property
    def count(self) -> int:
        """Get total number of embeddings in collection"""
        if not self._initialized:
            return 0
        try:
            return self._hybrid_service.count
        except Exception:
            return 0

    async def _ensure_initialized(self) -> bool:
        if not self._initialized:
            return await self.initialize()
        return True


# Singleton instance
_vector_store_service: Optional[VectorStoreService] = None


@lru_cache()
def get_vector_store_service() -> VectorStoreService:
    """Get singleton vector store service instance"""
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service

