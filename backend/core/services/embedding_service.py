"""
Embedding Service
文本向量化服务 - 支持OpenAI和本地模型
"""

import logging
from typing import List, Optional, Union
from functools import lru_cache

import numpy as np

from ..base_config import get_base_settings

settings = get_base_settings()

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    文本向量化服务
    支持:
    - OpenAI text-embedding-3-small/large
    - 本地模型 (如 BAAI/bge-large-zh-v1.5)
    """

    def __init__(self):
        self._openai_client = None
        self._local_model = None
        self._model_type: str = "openai"

        # Initialize based on configuration
        if settings.LOCAL_EMBEDDING_MODEL:
            self._init_local_model()
        elif settings.OPENAI_API_KEY:
            self._init_openai()
        else:
            logger.warning(
                "No embedding model configured. "
                "Set OPENAI_API_KEY or LOCAL_EMBEDDING_MODEL in config."
            )

    def _init_openai(self):
        """Initialize OpenAI embedding client"""
        try:
            from openai import OpenAI

            self._openai_client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
            )
            self._model_type = "openai"
            logger.info(f"Initialized OpenAI embedding: {settings.EMBEDDING_MODEL}")
        except ImportError:
            logger.error("openai package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")

    def _init_local_model(self):
        """Initialize local embedding model (sentence-transformers)"""
        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(
                settings.LOCAL_EMBEDDING_MODEL,
                device="cuda" if self._has_cuda() else "cpu",
            )
            self._model_type = "local"
            logger.info(f"Initialized local embedding: {settings.LOCAL_EMBEDDING_MODEL}")
        except ImportError:
            logger.error("sentence-transformers package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize local model: {e}")
            # Fallback to OpenAI
            if settings.OPENAI_API_KEY:
                self._init_openai()

    @staticmethod
    def _has_cuda() -> bool:
        """Check if CUDA is available"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text

        Args:
            text: Input text to embed

        Returns:
            List of float values (embedding vector), or None on error
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            if self._model_type == "openai" and self._openai_client:
                return await self._embed_openai(text)
            elif self._model_type == "local" and self._local_model:
                return self._embed_local(text)
            else:
                logger.error("No embedding model available")
                return None
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return None

    async def embed_texts(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts (batch)

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            if self._model_type == "openai" and self._openai_client:
                return await self._embed_openai_batch(texts)
            elif self._model_type == "local" and self._local_model:
                return self._embed_local_batch(texts)
            else:
                return [None] * len(texts)
        except Exception as e:
            logger.error(f"Batch embedding error: {e}")
            return [None] * len(texts)

    async def _embed_openai(self, text: str) -> Optional[List[float]]:
        """Generate embedding using OpenAI API"""
        import asyncio

        def _call_api():
            response = self._openai_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=text,
            )
            return response.data[0].embedding

        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, _call_api)
        return embedding

    async def _embed_openai_batch(
        self, texts: List[str]
    ) -> List[Optional[List[float]]]:
        """Generate embeddings using OpenAI API (batch)"""
        import asyncio

        def _call_api():
            response = self._openai_client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
            )
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [d.embedding for d in sorted_data]

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, _call_api)
        return embeddings

    def _embed_local(self, text: str) -> Optional[List[float]]:
        """Generate embedding using local model"""
        embedding = self._local_model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def _embed_local_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings using local model (batch)"""
        embeddings = self._local_model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    @property
    def dimension(self) -> int:
        """Get embedding dimension"""
        if self._model_type == "openai":
            return settings.EMBEDDING_DIMENSION
        elif self._local_model:
            return self._local_model.get_sentence_embedding_dimension()
        return settings.EMBEDDING_DIMENSION

    @property
    def model_name(self) -> str:
        """Get current model name"""
        if self._model_type == "openai":
            return settings.EMBEDDING_MODEL
        elif self._model_type == "local":
            return settings.LOCAL_EMBEDDING_MODEL or "unknown"
        return "none"

# Singleton instance
_embedding_service: Optional[EmbeddingService] = None

@lru_cache()
def get_embedding_service() -> EmbeddingService:
    """Get singleton embedding service instance"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
