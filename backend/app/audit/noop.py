from app.audit.store import AuditStore, AuditIdentity, AuditClarification
from app.models.contracts import TurnRecord

class NoopAuditStore(AuditStore):
    """
    A no-operation implementation of AuditStore.
    Used when Supabase is not configured.
    """
    
    async def start(self) -> None:
        pass
        
    async def stop(self) -> None:
        pass
        
    def enqueue_turn(self, turn: TurnRecord, identity: AuditIdentity, clarification: AuditClarification | None = None) -> None:
        pass
        
    def enqueue_feedback(self, turn_id: str, quality_flag: str) -> None:
        pass
        
    async def check_health(self) -> str:
        return "not_configured"
