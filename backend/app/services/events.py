from __future__ import annotations

from collections import defaultdict
from queue import Queue
from uuid import UUID

from pydantic import BaseModel

EventQueue = Queue[dict]


class PipelineEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[EventQueue]] = defaultdict(set)

    def connect(self, session_id: UUID) -> EventQueue:
        queue: EventQueue = Queue()
        self._subscribers[session_id].add(queue)
        return queue

    def disconnect(self, session_id: UUID, queue: EventQueue) -> None:
        self._subscribers[session_id].discard(queue)

    async def publish(self, session_id: UUID, event: BaseModel) -> None:
        payload = event.model_dump(mode="json")
        for queue in list(self._subscribers.get(session_id, set())):
            queue.put(payload)
