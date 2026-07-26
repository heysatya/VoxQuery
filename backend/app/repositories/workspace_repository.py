"""Durable Workspace Repository for pinned widgets persistence."""
from __future__ import annotations
import json
import logging
from typing import Any
from uuid import UUID
import asyncpg

from app.models.contracts import AuthClaims

logger = logging.getLogger("voxquery.repositories.workspace")


class WorkspaceRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_user_widgets(self, claims: AuthClaims) -> list[dict[str, Any]]:
        """Fetch user's pinned widgets with joined turn result data."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT w.id, w.turn_id, w.title, w.layout_x, w.layout_y, w.layout_w, w.layout_h, w.created_at,
                       t.chart_type, t.result_json, t.full_result
                FROM pinned_widgets w
                JOIN turns t ON t.turn_id = w.turn_id
                WHERE w.tenant_id = $1 AND w.user_id = $2
                ORDER BY w.created_at ASC
                """,
                claims.tenant_id, claims.user_id,
            )

        results = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("result_json"), str):
                d["result_json"] = json.loads(d["result_json"])
            if isinstance(d.get("full_result"), str):
                d["full_result"] = json.loads(d["full_result"])
            results.append(d)
        return results

    async def create_widget(
        self,
        claims: AuthClaims,
        turn_id: UUID,
        title: str,
        layout_x: int = 0,
        layout_y: int = 0,
        layout_w: int = 4,
        layout_h: int = 3,
    ) -> dict[str, Any]:
        """Pins a new widget to user's workspace."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO pinned_widgets (tenant_id, user_id, turn_id, title, layout_x, layout_y, layout_w, layout_h)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, turn_id, title, layout_x, layout_y, layout_w, layout_h, created_at
                """,
                claims.tenant_id, claims.user_id, turn_id, title, layout_x, layout_y, layout_w, layout_h,
            )
        return dict(row) if row else {}

    async def delete_widget(self, widget_id: UUID, claims: AuthClaims) -> bool:
        """Deletes a pinned widget scoped to user and tenant."""
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM pinned_widgets WHERE id = $1 AND tenant_id = $2 AND user_id = $3",
                widget_id, claims.tenant_id, claims.user_id,
            )
        return res != "DELETE 0"

    async def update_widget_layout(
        self,
        widget_id: UUID,
        claims: AuthClaims,
        layout_x: int,
        layout_y: int,
        layout_w: int,
        layout_h: int,
    ) -> bool:
        """Updates grid layout position and size for a pinned widget."""
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE pinned_widgets
                SET layout_x = $4, layout_y = $5, layout_w = $6, layout_h = $7
                WHERE id = $1 AND tenant_id = $2 AND user_id = $3
                """,
                widget_id, claims.tenant_id, claims.user_id, layout_x, layout_y, layout_w, layout_h,
            )
        return res != "UPDATE 0"
