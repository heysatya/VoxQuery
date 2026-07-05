from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.models.contracts import TurnRecord

@dataclass
class AuditIdentity:
    tenant_id: UUID
    tenant_name: str
    user_id: UUID
    email: str
    role: str
    snowflake_role: str
    conversation_id: UUID
    conversation_title: str

@dataclass
class AuditClarification:
    turn_id: UUID
    prompt_sent: str
    user_choice: str | None
    resolution_type: str

class AuditStore(Protocol):
    """
    Protocol for asynchronously persisting audit records (turns, clarifications, feedback).
    Implementations must be thread-safe as they will be accessed from the FastAPI event loop
    and background worker threads.
    """
    
    async def start(self) -> None:
        """Initialize the store (e.g., connect to database)."""
        ...
        
    async def stop(self) -> None:
        """Shutdown the store (e.g., close connections)."""
        ...
        
    def enqueue_turn(self, turn: TurnRecord, identity: AuditIdentity, clarification: AuditClarification | None = None) -> None:
        """
        Synchronously enqueue a TurnRecord, its Identity context, and an optional Clarification for persistence.
        Implementations must strip `full_result` to prevent raw data leakage and must never raise exceptions into the pipeline.
        """
        ...
        
    def enqueue_feedback(self, turn_id: str, quality_flag: str) -> None:
        """
        Synchronously enqueue a feedback update for a turn.
        """
        ...
        
    async def check_health(self) -> str:
        """
        Check the health of the store.
        Returns "not_configured" (Noop), "ok" (Success < 100ms), or "degraded" (Timeout/Error).
        """
        ...
