"""
vector_store.py
────────────────
FAISS-based vector store for dense similarity search.

Design decisions:
- IndexFlatIP (inner product) for cosine similarity on normalized vectors
- Chunks stored separately in JSONL (FAISS only stores floats)
- Atomic save: write to temp file then rename to prevent corruption
- Thread-safe search via FAISS's own thread safety
- Simple integer-based ID mapping (FAISS uses int64 IDs)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import settings
from app.metadata.models import RagChunk, RetrievedChunk

logger = logging.getLogger(__name__)


class FAISSVectorStore:
    """
    FAISS-based vector index with JSONL chunk persistence.

    Architecture:
        - FAISS index: stores float32 vectors keyed by int64 position
        - JSONL file: stores chunk data keyed by position (matching FAISS)
        - In-memory chunk list: for fast lookup by position

    Usage:
        store = FAISSVectorStore(dim=384)

        # Build index
        store.add_chunks(chunks, embeddings)
        store.save()

        # Load and search
        store.load()
        results = store.search(query_vector, top_k=10)
    """

    def __init__(
        self,
        dim: int,
        index_path: Optional[str] = None,
        chunks_path: Optional[str] = None,
    ):
        """
        Initialize the vector store.

        Args:
            dim: Vector dimension (must match embedding model)
            index_path: Path to save/load FAISS index
            chunks_path: Path to save/load chunk JSONL
        """
        try:
            import faiss
            self.faiss = faiss
        except ImportError:
            raise ImportError(
                "faiss-cpu required. Install with: pip install faiss-cpu"
            )

        self.dim = dim
        self.index_path = Path(index_path or settings.faiss_index_path)
        self.chunks_path = Path(chunks_path or settings.faiss_chunks_path)

        # Initialize inner product index
        # For cosine similarity: normalize vectors BEFORE adding
        self.index = self.faiss.IndexFlatIP(dim)

        # Parallel chunk storage (position in index = position in list)
        self._chunks: list[RagChunk] = []

        logger.info(
            "FAISSVectorStore initialized: dim=%d, index_path=%s",
            dim,
            self.index_path,
        )

    @property
    def num_chunks(self) -> int:
        """Number of chunks in the index."""
        return self.index.ntotal

    @property
    def is_empty(self) -> bool:
        return self.num_chunks == 0

    def add_chunks(
        self,
        chunks: list[RagChunk],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add chunks and their embeddings to the index.

        Args:
            chunks: RagChunk objects to index
            embeddings: Corresponding embedding vectors (must be normalized)
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) "
                f"must have the same length"
            )

        if not chunks:
            logger.warning("add_chunks called with empty list")
            return

        # Convert to numpy and normalize for cosine similarity
        vectors = np.array(embeddings, dtype=np.float32)
        faiss_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Avoid division by zero for zero vectors
        faiss_norms = np.where(faiss_norms == 0, 1.0, faiss_norms)
        vectors = vectors / faiss_norms

        # Add to FAISS index
        self.index.add(vectors)

        # Store chunks in parallel list
        self._chunks.extend(chunks)

        logger.info(
            "Added %d chunks to FAISS index (total: %d)",
            len(chunks),
            self.num_chunks,
        )

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        score_threshold: float = 0.0,
    ) -> list[RetrievedChunk]:
        """
        Search for the most similar chunks.

        Args:
            query_vector: Embedded query (should be normalized)
            top_k: Number of results to return
            score_threshold: Minimum similarity score (0.0 to 1.0)

        Returns:
            List of RetrievedChunks, ordered by similarity (highest first)
        """
        if self.is_empty:
            logger.warning("Vector store is empty. Run indexing first.")
            return []

        # Normalize query vector
        q = np.array([query_vector], dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        # Clamp top_k to available chunks
        actual_k = min(top_k, self.num_chunks)

        # Execute FAISS search
        scores, indices = self.index.search(q, actual_k)

        results: list[RetrievedChunk] = []
        for score, idx in zip(scores[0], indices[0]):
            # FAISS returns -1 for unfilled results
            if idx == -1:
                continue

            # Apply score threshold
            if float(score) < score_threshold:
                continue

            chunk = self._chunks[idx]
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=float(score),
                    vector_score=float(score),
                    source="vector",
                )
            )

        return results

    def save(self) -> None:
        """
        Persist index and chunks to disk atomically.
        Uses temp-then-rename pattern to prevent corruption.
        """
        # Ensure directories exist
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.chunks_path.parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index atomically
        tmp_index = self.index_path.with_suffix(".tmp")
        self.faiss.write_index(self.index, str(tmp_index))
        tmp_index.rename(self.index_path)

        # Save chunks as JSONL atomically
        tmp_chunks = self.chunks_path.with_suffix(".tmp")
        with open(tmp_chunks, "w", encoding="utf-8") as f:
            for chunk in self._chunks:
                f.write(chunk.model_dump_json() + "\n")
        tmp_chunks.rename(self.chunks_path)

        logger.info(
            "Saved vector store: %d vectors → %s",
            self.num_chunks,
            self.index_path,
        )

    def load(self) -> None:
        """
        Load index and chunks from disk.

        Raises:
            FileNotFoundError: If index or chunks file does not exist
        """
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"FAISS index not found at '{self.index_path}'. "
                f"Run index_pipeline.py first."
            )

        if not self.chunks_path.exists():
            raise FileNotFoundError(
                f"Chunks file not found at '{self.chunks_path}'. "
                f"Run index_pipeline.py first."
            )

        # Load FAISS index
        self.index = self.faiss.read_index(str(self.index_path))

        # Load chunks from JSONL
        self._chunks = []
        with open(self.chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunk = RagChunk.model_validate_json(line)
                    self._chunks.append(chunk)

        # Verify alignment
        if self.index.ntotal != len(self._chunks):
            raise ValueError(
                f"Index/chunk mismatch: {self.index.ntotal} vectors "
                f"but {len(self._chunks)} chunks"
            )

        logger.info(
            "Loaded vector store: %d vectors from '%s'",
            self.num_chunks,
            self.index_path,
        )

    def reset(self) -> None:
        """Clear all vectors and chunks from memory."""
        self.index = self.faiss.IndexFlatIP(self.dim)
        self._chunks = []
        logger.info("Vector store reset")

    def get_stats(self) -> dict:
        """Return index statistics."""
        return {
            "num_chunks": self.num_chunks,
            "dimension": self.dim,
            "index_path": str(self.index_path),
            "chunks_path": str(self.chunks_path),
            "index_file_exists": self.index_path.exists(),
            "chunks_file_exists": self.chunks_path.exists(),
        }
