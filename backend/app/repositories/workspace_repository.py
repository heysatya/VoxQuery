"""Durable Workspace Repository for pinned widgets persistence."""

from __future__ import annotations
import json
import logging
from typing import Any
from uuid import UUID
import asyncpg

from app.models.contracts import AuthClaims

logger = logging.getLogger("voxquery.repositories.workspace")


def _normalise_widget(row: Any) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("snapshot_result_json"), str):
        data["snapshot_result_json"] = json.loads(data["snapshot_result_json"])
    result = data.get("snapshot_result_json")
    data["result"] = result
    data["data_status"] = "available" if result is not None else "no_snapshot"
    data["saved_at"] = data.get("snapshot_taken_at") or data.get("created_at")
    return data


class WorkspaceRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_user_widgets(self, claims: AuthClaims) -> list[dict[str, Any]]:
        """Fetch user's pinned widgets from snapshot columns (no JOIN required)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, turn_id, title, note, layout_x, layout_y, layout_w, layout_h, created_at,
                       original_question, chart_type, snapshot_result_json, snapshot_narrative,
                       snapshot_generated_sql, snapshot_taken_at, snapshot_headline_value, snapshot_headline_label
                FROM pinned_widgets
                WHERE tenant_id = $1 AND user_id = $2
                ORDER BY created_at ASC
                LIMIT 50
                """,
                claims.tenant_id,
                claims.user_id,
            )
        return [_normalise_widget(row) for row in rows]

    async def create_widget(
        self,
        claims: AuthClaims,
        turn_id: UUID,
        title: str,
        note: str | None = None,
        headline_value: float | None = None,
        headline_label: str | None = None,
        layout_x: int = 0,
        layout_y: int = 0,
        layout_w: int = 4,
        layout_h: int = 3,
    ) -> dict[str, Any] | None:
        """Pins a new widget as a true snapshot, capturing all result data at pin time."""
        async with self._pool.acquire() as conn:
            source = await conn.fetchrow(
                """
                SELECT turn_id, user_input, chart_type, full_result, generated_sql
                FROM turns
                WHERE turn_id = $1 AND tenant_id = $2 AND completed = TRUE
                """,
                turn_id,
                claims.tenant_id,
            )
            if source is None:
                raise ValueError("Cannot pin: source turn not found or not yet completed.")
            full_result = (
                json.loads(source["full_result"])
                if isinstance(source["full_result"], str)
                else source["full_result"]
            )
            if not full_result:
                raise ValueError(
                    "Cannot pin: this result has no data to save yet. Try again in a moment."
                )

            row = await conn.fetchrow(
                """
                INSERT INTO pinned_widgets (
                    tenant_id, user_id, turn_id, title, note, layout_x, layout_y, layout_w, layout_h,
                    original_question, chart_type, snapshot_result_json, snapshot_generated_sql,
                    snapshot_taken_at, snapshot_headline_value, snapshot_headline_label
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13, now(), $14, $15)
                ON CONFLICT (tenant_id, user_id, turn_id) DO UPDATE SET title = EXCLUDED.title
                RETURNING *
                """,
                claims.tenant_id,
                claims.user_id,
                turn_id,
                title,
                note,
                layout_x,
                layout_y,
                layout_w,
                layout_h,
                source["user_input"],
                source["chart_type"],
                json.dumps(full_result),
                source["generated_sql"],
                headline_value,
                headline_label,
            )
        return _normalise_widget(row) if row else None

    async def get_widget(self, widget_id: UUID, claims: AuthClaims) -> dict[str, Any] | None:
        """Fetch a single pinned widget scoped to user and tenant."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM pinned_widgets WHERE id = $1 AND tenant_id = $2 AND user_id = $3",
                widget_id,
                claims.tenant_id,
                claims.user_id,
            )
        return _normalise_widget(row) if row else None

    async def delete_widget(self, widget_id: UUID, claims: AuthClaims) -> bool:
        """Deletes a pinned widget scoped to user and tenant."""
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM pinned_widgets WHERE id = $1 AND tenant_id = $2 AND user_id = $3",
                widget_id,
                claims.tenant_id,
                claims.user_id,
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
                widget_id,
                claims.tenant_id,
                claims.user_id,
                layout_x,
                layout_y,
                layout_w,
                layout_h,
            )
        return res != "UPDATE 0"

    async def update_widget_note(
        self,
        widget_id: UUID,
        claims: AuthClaims,
        note: str | None,
    ) -> bool:
        """Updates the note on a pinned widget."""
        async with self._pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE pinned_widgets
                SET note = $4
                WHERE id = $1 AND tenant_id = $2 AND user_id = $3
                """,
                widget_id,
                claims.tenant_id,
                claims.user_id,
                note,
            )
        return res != "UPDATE 0"
