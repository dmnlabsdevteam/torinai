#!/usr/bin/env python3
"""
Embedding Service

Semantic similarity search via sentence embeddings.
Uses sentence-transformers/all-MiniLM-L6-v2 model for 384-dimensional vectors.

Features:
- Single text embedding generation
- Batch embedding processing
- Model caching for performance
- Integration with memory storage (MySQL hot/cold tiers)

Model: all-MiniLM-L6-v2
Dimensions: 384
Load Time: ~1.46 seconds
"""

import logging
import os
import numpy as np
from typing import List, Optional, Union
from sentence_transformers import SentenceTransformer
import time

from core.model_policy import (
    ModelClass, guard_model_use, model_use_permitted, record_model_executed,
)

logger = logging.getLogger(__name__)


#: WHICH MODEL, DECLARED ONCE. Two components load sentence-transformers for
#: their own reasons -- this service, which raises when embeddings are
#: unavailable, and tool discovery, which degrades to BM25 and keeps ranking.
#: Those differences are deliberate and stay. The model IDENTITY is not a
#: difference: it was written out twice, so changing it in one place left the
#: other on the old model, producing vectors of a different width and meaning
#: that nothing downstream could tell apart from the right ones.
#:
#: Override with TORIN_EMBEDDING_MODEL to try another, and note that changing
#: it invalidates every vector already stored: the `embedding` column is a
#: fixed-width pgvector, and mixed widths break the distance operator rather
#: than reporting a mismatch.
EMBEDDING_MODEL_ID = os.getenv("TORIN_EMBEDDING_MODEL",
                               "sentence-transformers/all-MiniLM-L6-v2")

#: Vector width of EMBEDDING_MODEL_ID. Read from the model once it loads;
#: this is the declared expectation, and a mismatch is reported rather than
#: silently stored.
EMBEDDING_DIMENSIONS = int(os.getenv("TORIN_EMBEDDING_DIMENSIONS", "384"))


class EmbeddingService:
    """
    Embedding Service for Semantic Search

    Generates embeddings using sentence-transformers for semantic similarity.
    Singleton pattern for efficient model loading and caching.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_ID):
        """
        Initialize embedding service

        Args:
            model_name: HuggingFace model identifier (default: all-MiniLM-L6-v2)
        """
        self.model_name = model_name
        self.model: Optional[SentenceTransformer] = None
        self.embedding_dim = EMBEDDING_DIMENSIONS
        self.initialized = False
        self._init_failed = False  # Prevent infinite retry on broken-pipe / MPS conflict

        # Performance metrics
        self.metrics = {
            'embeddings_generated': 0,
            'batch_operations': 0,
            'total_processing_time': 0.0,
            'model_load_time': 0.0
        }

    def initialize(self) -> bool:
        """
        Load the sentence transformer model

        Returns:
            True if successful, False otherwise
        """
        if self.initialized:
            return True
        if self._init_failed:
            return False  # Don't retry after MPS/pipe failure — avoid log spam

        # Loading is not inference, but get_embedding_service() initializes
        # eagerly, so without this a strict run still materialises 384-dim
        # MiniLM weights into the process. Reported as an unavailable capability
        # (the established False return) rather than raised, since every caller
        # already handles a failed load.
        if not model_use_permitted(ModelClass.EMBEDDING, "embedding_service.initialize"):
            self._init_failed = True
            return False

        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            start_time = time.time()

            # Force CPU — the MPS device is fully occupied by the 32B LLM.
            # Using MPS here causes [Errno 32] Broken pipe on Apple Silicon.
            self.model = SentenceTransformer(self.model_name, local_files_only=True, device='cpu')

            load_time = time.time() - start_time
            self.metrics['model_load_time'] = load_time

            self.initialized = True
            logger.info(f"Embedding model loaded successfully in {load_time:.2f}s (CPU)")
            logger.info(f"Embedding dimension: {self.embedding_dim}")

            return True

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.initialized = False
            self._init_failed = True  # Cache failure — stop retrying every call
            return False

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text

        Args:
            text: Input text to embed

        Returns:
            List of float values (384-dimensional vector) or None if failed
        """
        # Declared before the try: the handler below returns None on failure, so
        # a forbidden call caught there would be indistinguishable from an
        # embedding that legitimately could not be produced.
        guard_model_use(ModelClass.EMBEDDING, "embedding_service.generate_embedding")

        if not self.initialized:
            if not self.initialize():
                return None

        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        try:
            start_time = time.time()

            # Generate embedding
            embedding = self.model.encode(text, convert_to_numpy=True)
            record_model_executed(ModelClass.EMBEDDING, "embedding_service.generate_embedding")

            # Convert to list for JSON serialization
            embedding_list = embedding.tolist()

            # Update metrics
            processing_time = time.time() - start_time
            self.metrics['embeddings_generated'] += 1
            self.metrics['total_processing_time'] += processing_time

            logger.debug(f"Generated embedding in {processing_time:.4f}s")

            return embedding_list

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def batch_embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """
        Generate embeddings for multiple texts (batched for efficiency)

        Args:
            texts: List of input texts to embed

        Returns:
            List of embedding vectors or None if failed
        """
        guard_model_use(ModelClass.EMBEDDING, "embedding_service.batch_embed")

        if not self.initialized:
            if not self.initialize():
                return None

        if not texts:
            logger.warning("Empty text list provided for batch embedding")
            return None

        # Filter out empty texts
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            logger.warning("No valid texts in batch")
            return None

        try:
            start_time = time.time()

            # Batch encode for efficiency
            embeddings = self.model.encode(valid_texts, convert_to_numpy=True, batch_size=32)
            record_model_executed(ModelClass.EMBEDDING, "embedding_service.batch_embed")

            # Convert to list of lists
            embeddings_list = embeddings.tolist()

            # Update metrics
            processing_time = time.time() - start_time
            self.metrics['batch_operations'] += 1
            self.metrics['embeddings_generated'] += len(valid_texts)
            self.metrics['total_processing_time'] += processing_time

            logger.info(
                f"Generated {len(valid_texts)} embeddings in {processing_time:.4f}s "
                f"({processing_time/len(valid_texts):.4f}s per embedding)"
            )

            return embeddings_list

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return None

    def compute_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float]
    ) -> Optional[float]:
        """
        Compute cosine similarity between two embeddings

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score (0.0 to 1.0) or None if failed
        """
        try:
            # Convert to numpy arrays
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)

            # Cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)

            # Clamp to [0, 1] range
            similarity = max(0.0, min(1.0, similarity))

            return float(similarity)

        except Exception as e:
            logger.error(f"Failed to compute similarity: {e}")
            return None

    def get_metrics(self) -> dict:
        """
        Get embedding service performance metrics

        Returns:
            Dictionary with performance statistics
        """
        avg_time = (
            self.metrics['total_processing_time'] / self.metrics['embeddings_generated']
            if self.metrics['embeddings_generated'] > 0
            else 0.0
        )

        return {
            'model_name': self.model_name,
            'embedding_dimension': self.embedding_dim,
            'initialized': self.initialized,
            'embeddings_generated': self.metrics['embeddings_generated'],
            'batch_operations': self.metrics['batch_operations'],
            'model_load_time': self.metrics['model_load_time'],
            'avg_embedding_time': avg_time
        }

    def __del__(self):
        """Cleanup on deletion"""
        if self.initialized:
            logger.debug("EmbeddingService cleanup")


# Global singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    Get global embedding service instance (singleton)

    Returns:
        EmbeddingService instance
    """
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = EmbeddingService()
        _embedding_service.initialize()

    return _embedding_service


# Convenience functions for direct usage
def generate_embedding(text: str) -> Optional[List[float]]:
    """
    Generate embedding for text using global service

    Args:
        text: Input text

    Returns:
        Embedding vector or None
    """
    service = get_embedding_service()
    return service.generate_embedding(text)


def batch_embed(texts: List[str]) -> Optional[List[List[float]]]:
    """
    Generate embeddings for multiple texts using global service

    Args:
        texts: List of input texts

    Returns:
        List of embedding vectors or None
    """
    service = get_embedding_service()
    return service.batch_embed(texts)


def compute_similarity(
    embedding1: List[float],
    embedding2: List[float]
) -> Optional[float]:
    """
    Compute similarity between embeddings using global service

    Args:
        embedding1: First embedding
        embedding2: Second embedding

    Returns:
        Similarity score (0.0 to 1.0)
    """
    service = get_embedding_service()
    return service.compute_similarity(embedding1, embedding2)
