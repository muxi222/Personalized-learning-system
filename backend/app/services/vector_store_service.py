"""
Vector Store Service
向量数据库服务 - 支持ChromaDB
"""

import logging
from typing import List, Optional, Dict, Any
from functools import lru_cache

from ..core.config import settings

logger = logging.getLogger(__name__)


class VectorStoreService:
    """
    向量数据库服务
    支持:
    - ChromaDB (本地持久化或HTTP客户端)
    """

    def __init__(self):
        self._client = None
        self._collection = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize vector store connection"""
        if self._initialized:
            return True

        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            # Check if using HTTP client (for docker deployment)
            if settings.VECTOR_STORE_HOST != "localhost" or settings.APP_ENV == "production":
                self._client = chromadb.HttpClient(
                    host=settings.VECTOR_STORE_HOST,
                    port=settings.VECTOR_STORE_PORT,
                )
                logger.info(
                    f"Connected to ChromaDB HTTP: "
                    f"{settings.VECTOR_STORE_HOST}:{settings.VECTOR_STORE_PORT}"
                )
            else:
                # Local persistent client
                import os
                os.makedirs(settings.VECTOR_STORE_PATH, exist_ok=True)

                self._client = chromadb.PersistentClient(
                    path=settings.VECTOR_STORE_PATH,
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    ),
                )
                logger.info(f"Using local ChromaDB: {settings.VECTOR_STORE_PATH}")

            # Get or create collection
            self._collection = self._client.get_or_create_collection(
                name=settings.VECTOR_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # Use cosine similarity
            )
            self._initialized = True
            logger.info(f"Initialized collection: {settings.VECTOR_COLLECTION_NAME}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
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
        if not self._initialized:
            await self.initialize()

        try:
            self._collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[metadata] if metadata else None,
                documents=[document] if document else None,
            )
            logger.debug(f"Added embedding for doc_id: {doc_id}")
            return True
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
        if not self._initialized:
            await self.initialize()

        try:
            self._collection.upsert(
                ids=doc_ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
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
        if not self._initialized:
            await self.initialize()

        include = include or ["metadatas", "distances", "documents"]

        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where,
                include=include,
            )

            # Format results
            formatted = []
            if results and results["ids"]:
                for i, doc_id in enumerate(results["ids"][0]):
                    item = {"id": doc_id}
                    if "distances" in results and results["distances"]:
                        # Convert distance to similarity score (for cosine)
                        item["score"] = 1 - results["distances"][0][i]
                    if "metadatas" in results and results["metadatas"]:
                        item["metadata"] = results["metadatas"][0][i]
                    if "documents" in results and results["documents"]:
                        item["document"] = results["documents"][0][i]
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
        if not self._initialized:
            await self.initialize()

        try:
            self._collection.delete(ids=[doc_id])
            logger.debug(f"Deleted embedding for doc_id: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete embedding: {e}")
            return False

    async def get_embedding(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get embedding and metadata by document ID"""
        if not self._initialized:
            await self.initialize()

        try:
            result = self._collection.get(
                ids=[doc_id],
                include=["embeddings", "metadatas", "documents"],
            )
            if result and result["ids"]:
                return {
                    "id": result["ids"][0],
                    "embedding": result["embeddings"][0] if result["embeddings"] else None,
                    "metadata": result["metadatas"][0] if result["metadatas"] else None,
                    "document": result["documents"][0] if result["documents"] else None,
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            return None

    @property
    def count(self) -> int:
        """Get total number of embeddings in collection"""
        if not self._initialized:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0


# Singleton instance
_vector_store_service: Optional[VectorStoreService] = None


@lru_cache()
def get_vector_store_service() -> VectorStoreService:
    """Get singleton vector store service instance"""
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service

