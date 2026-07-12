from __future__ import annotations

import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi


class BM25Index:
    def __init__(self) -> None:
        self._corpus: list[list[str]] = []
        self._ids: list[int] = []
        self._bm25: BM25Okapi | None = None

    def add(self, texts: list[str], ids: list[int]) -> None:
        tokenized = [t.lower().split() for t in texts]
        self._corpus.extend(tokenized)
        self._ids.extend(ids)
        self._bm25 = BM25Okapi(self._corpus)

    def search(self, query: str, k: int = 10) -> list[int]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(query.lower().split())
        top_indices = sorted(range(len(scores)),
                             key=lambda i: scores[i], reverse=True)[:k]
        return [self._ids[i] for i in top_indices]

    def save(self, path: str | Path) -> None:
        with open(path, "wb") as f:
            pickle.dump((self._corpus, self._ids), f)

    @classmethod
    def load(cls, path: str | Path) -> "BM25Index":
        idx = cls()
        with open(path, "rb") as f:
            corpus, ids = pickle.load(f)
        idx._corpus = corpus
        idx._ids = ids
        idx._bm25 = BM25Okapi(corpus)
        return idx
