from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any


class Observability:
    @asynccontextmanager
    async def span(self, name: str, **metadata: Any):
        yield

    async def score(self, name: str, value: int, **metadata: Any) -> None:
        return None


class NoopObservability(Observability):
    pass
