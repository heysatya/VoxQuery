from __future__ import annotations

from openai import OpenAI


class Reranker:
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = "") -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key)

    def rerank(self, query: str, chunks: list[str], top_n: int = 5) -> list[int]:
        """Return indices of the top-*n* most relevant chunks."""
        if not chunks:
            return []
        numbered = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks))
        prompt = (
            f"Query: {query}\n\n"
            f"Rank the following schema chunks by relevance (most relevant first).\n"
            f"Return only the bracket numbers separated by commas.\n\n{numbered}"
        )
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        indices = []
        for token in raw.split(","):
            token = token.strip().strip("[]")
            if token.isdigit():
                indices.append(int(token))
        return indices[:top_n]
