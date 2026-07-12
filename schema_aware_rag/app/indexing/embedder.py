"""
embedder.py
───────────
Dual-mode embedder supporting OpenAI and local BGE models.

Design decisions:
- Abstract base class makes provider swap trivial
- Batch processing to respect rate limits and throughput
- Caching at this layer prevents re-embedding identical texts
- Dimension configured per model to match FAISS index
- Retry logic with exponential backoff for API calls
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Abstract Base
# ─────────────────────────────────────────────────────────────────────


class BaseEmbedder(ABC):
    """Abstract base class for all embedding providers."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts into dense vectors.

        Args:
            texts: List of strings to embed

        Returns:
            List of float vectors, one per input text
        """
        ...

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """
        Embed a single query string.
        May use a query-specific prompt for asymmetric models.

        Args:
            query: User question string

        Returns:
            Single float vector
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension for this embedding model."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        ...


# ─────────────────────────────────────────────────────────────────────
# OpenAI Embedder
# ─────────────────────────────────────────────────────────────────────


class OpenAIEmbedder(BaseEmbedder):
    """
    OpenAI text-embedding-3-small embedder.

    Best for: production use, highest quality
    Cost: $0.02 per 1M tokens
    Requires: OPENAI_API_KEY in environment
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        batch_size: int = 100,
        max_retries: int = 3,
    ):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            )

        api_key = settings.openai_api_key
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. Either set it in .env "
                "or use EMBEDDING_PROVIDER=local"
            )

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self._dimension = dimensions
        self.batch_size = batch_size
        self.max_retries = max_retries

        logger.info(
            "OpenAI embedder initialized: model=%s, dim=%d",
            self.model,
            self._dimension,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def provider_name(self) -> str:
        return f"openai/{self.model}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed texts in batches to respect OpenAI API limits.

        Args:
            texts: Texts to embed (will be cleaned automatically)

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Clean texts
        cleaned = [t.replace("\n", " ").strip() for t in texts]

        all_embeddings: list[list[float]] = []

        # Process in batches
        for i in range(0, len(cleaned), self.batch_size):
            batch = cleaned[i: i + self.batch_size]
            batch_embeddings = self._embed_batch_with_retry(batch)
            all_embeddings.extend(batch_embeddings)

            logger.debug(
                "Embedded batch %d/%d (%d texts)",
                i // self.batch_size + 1,
                (len(cleaned) + self.batch_size - 1) // self.batch_size,
                len(batch),
            )

        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        embeddings = self.embed_texts([query])
        return embeddings[0]

    def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch with retry logic."""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=texts,
                    dimensions=self._dimension,
                )
                return [item.embedding for item in response.data]

            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(
                    "OpenAI embedding attempt %d/%d failed: %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    self.max_retries,
                    e,
                    wait_time,
                )
                time.sleep(wait_time)

        raise RuntimeError(
            f"OpenAI embedding failed after {self.max_retries} attempts: "
            f"{last_error}"
        )


# ─────────────────────────────────────────────────────────────────────
# Local BGE Embedder
# ─────────────────────────────────────────────────────────────────────


class LocalBGEEmbedder(BaseEmbedder):
    """
    Local BGE (BAAI General Embedding) embedder using sentence-transformers.

    Best for: offline use, no API costs, compliance requirements
    Model: BAAI/bge-small-en-v1.5 (default, 384-dim, fast)
    Alternative: BAAI/bge-large-en-v1.5 (1024-dim, higher quality)
    """

    # BGE models use an instruction prefix for queries (not documents)
    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        batch_size: int = 32,
        device: str = "cpu",
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers required. "
                "Install with: pip install sentence-transformers"
            )

        logger.info(
            "Loading local BGE model: %s (this may take a moment...)", model_name)
        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size

        # Get actual dimension from model
        test_embedding = self.model.encode(["test"], normalize_embeddings=True)
        self._dimension = test_embedding.shape[1]

        logger.info(
            "Local BGE embedder ready: model=%s, dim=%d, device=%s",
            model_name,
            self._dimension,
            device,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def provider_name(self) -> str:
        return f"local/{self.model_name}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed texts using local model.
        Documents do NOT get the query instruction prefix.
        """
        if not texts:
            return []

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,   # L2 normalize for cosine similarity
            show_progress_bar=len(texts) > 50,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """
        Embed a query with BGE's instruction prefix.
        BGE uses asymmetric embedding (query vs document have different prompts).
        """
        prefixed_query = self.QUERY_INSTRUCTION + query
        embeddings = self.model.encode(
            [prefixed_query],
            normalize_embeddings=True,
        )
        return embeddings[0].tolist()


# ─────────────────────────────────────────────────────────────────────
# Cache Wrapper
# ─────────────────────────────────────────────────────────────────────


class CachedEmbedder(BaseEmbedder):
    """
    Wraps any embedder with a file-based cache.
    Prevents re-embedding identical texts across indexing runs.

    Cache format: pickle file mapping text_hash -> vector
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        cache_path: str = "data/indexes/embedding_cache.pkl",
    ):
        self.embedder = embedder
        self.cache_path = Path(cache_path)
        self._cache: dict[str, list[float]] = {}
        self._load_cache()

    @property
    def dimension(self) -> int:
        return self.embedder.dimension

    @property
    def provider_name(self) -> str:
        return f"cached/{self.embedder.provider_name}"

    def _text_hash(self, text: str) -> str:
        """Generate a cache key for a text string."""
        # Include provider name to invalidate cache on model change
        key = f"{self.embedder.provider_name}:{text}"
        return hashlib.sha256(key.encode()).hexdigest()

    def _load_cache(self) -> None:
        """Load cache from disk if it exists."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "rb") as f:
                    self._cache = pickle.load(f)
                logger.info(
                    "Loaded embedding cache: %d entries from '%s'",
                    len(self._cache),
                    self.cache_path,
                )
            except Exception as e:
                logger.warning("Could not load embedding cache: %s", e)
                self._cache = {}
        else:
            self._cache = {}

    def _save_cache(self) -> None:
        """Persist cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "wb") as f:
            pickle.dump(self._cache, f)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Return cached embeddings where available, embed misses.
        """
        hashes = [self._text_hash(t) for t in texts]

        # Separate cache hits from misses
        results: list[Optional[list[float]]] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        for i, (text, h) in enumerate(zip(texts, hashes)):
            if h in self._cache:
                results[i] = self._cache[h]
            else:
                miss_indices.append(i)
                miss_texts.append(text)

        cache_hits = len(texts) - len(miss_indices)
        logger.debug(
            "Embedding cache: %d hits, %d misses (%.0f%% hit rate)",
            cache_hits,
            len(miss_indices),
            (cache_hits / len(texts) * 100) if texts else 0,
        )

        # Embed misses
        if miss_texts:
            new_embeddings = self.embedder.embed_texts(miss_texts)
            for i, (idx, h, emb) in enumerate(
                zip(miss_indices, [hashes[i]
                    for i in miss_indices], new_embeddings)
            ):
                results[idx] = emb
                self._cache[h] = emb

            # Persist updated cache
            self._save_cache()

        return [r for r in results if r is not None]

    def embed_query(self, query: str) -> list[float]:
        """Queries are NOT cached (they change too frequently)."""
        return self.embedder.embed_query(query)

    @property
    def cache_size(self) -> int:
        """Number of cached embeddings."""
        return len(self._cache)


# ─────────────────────────────────────────────────────────────────────
# Factory Function
# ─────────────────────────────────────────────────────────────────────


def create_embedder(use_cache: bool = True) -> BaseEmbedder:
    """
    Factory function that creates the appropriate embedder
    based on settings.

    Args:
        use_cache: Whether to wrap with caching layer

    Returns:
        Configured embedder instance
    """
    provider = settings.embedding_provider.lower()

    if provider == "openai":
        settings.validate_for_openai()
        embedder: BaseEmbedder = OpenAIEmbedder(
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
    elif provider == "local":
        embedder = LocalBGEEmbedder(
            model_name=settings.local_embedding_model,
        )
    else:
        raise ValueError(
            f"Unknown embedding provider: '{provider}'. "
            f"Use 'openai' or 'local'."
        )

    if use_cache:
        embedder = CachedEmbedder(embedder)
        logger.info("Embedding cache enabled")

    return embedder
