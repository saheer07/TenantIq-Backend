"""
RAG Embeddings Module
Uses sentence-transformers (FREE, runs locally - no API key needed)
Replaces OpenAI embeddings to avoid quota/billing issues
"""

import os
import time
import math
from typing import List, Optional
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Generates embeddings using sentence-transformers (FREE, local)
    Drop-in replacement for OpenAI embeddings
    """

    def __init__(self, model: str = None):
        """
        Initialize embedding generator with local sentence-transformer model

        Args:
            model: Model name (defaults to settings.EMBEDDING_MODEL)
        """
        self.model_name = model or getattr(settings, 'EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
        self.embedding_dimension = getattr(settings, 'EMBEDDING_DIMENSION', 384)
        self._model = None  # lazy load

        logger.info(f"EmbeddingGenerator initialized with model: {self.model_name}")

    def _load_model(self):
        """Lazy load the model on first use"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading sentence-transformer model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"Model loaded successfully")
            except ImportError:
                raise ImportError(
                    "sentence-transformers is not installed. "
                    "Run: pip install sentence-transformers"
                )
        return self._model

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        try:
            model = self._load_model()
            embedding = model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            raise Exception(f"Failed to generate embedding: {str(e)}")

    def generate_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = 32
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            model = self._load_model()
            logger.info(f"Generating embeddings for {len(texts)} texts in batches of {batch_size}")

            all_embeddings = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                batch_embeddings = model.encode(batch, convert_to_tensor=False)
                all_embeddings.extend([emb.tolist() for emb in batch_embeddings])
                logger.info(f"Processed batch {i // batch_size + 1}/{(len(texts) - 1) // batch_size + 1}")

            return all_embeddings

        except Exception as e:
            raise Exception(f"Failed to generate batch embeddings: {str(e)}")

    def get_embedding_dimension(self) -> int:
        """Return the dimension of embeddings produced by this model"""
        return self.embedding_dimension


class CachedEmbeddingGenerator(EmbeddingGenerator):
    """
    Embedding generator with simple in-memory caching
    """

    def __init__(self, model: str = None):
        super().__init__(model)
        self._cache = {}

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding with caching"""
        cache_key = hash(text)

        if cache_key in self._cache:
            return self._cache[cache_key]

        embedding = super().generate_embedding(text)
        self._cache[cache_key] = embedding
        return embedding

    def clear_cache(self):
        """Clear the embedding cache"""
        self._cache.clear()

    def cache_size(self) -> int:
        """Return the number of cached embeddings"""
        return len(self._cache)


# ==================== Utility functions ====================

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    if len(vec1) != len(vec2):
        raise ValueError("Vectors must have the same dimension")

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


def validate_embedding(embedding: List[float], expected_dim: int = 384) -> bool:
    """Validate an embedding vector"""
    if not isinstance(embedding, list):
        return False
    if len(embedding) != expected_dim:
        return False
    if not all(isinstance(x, (int, float)) for x in embedding):
        return False
    return True


def estimate_embedding_cost(num_tokens: int, model: str = "local") -> float:
    """Free! sentence-transformers runs locally with no API cost"""
    return 0.0