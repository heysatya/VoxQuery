"""
Executive Memory Graph Service (PRD V2.2 Feature 2).

Constructs the session lineage used by the executive analysis recap. The API keeps
technical relationships available for advanced consumers while the primary UI presents
business questions, metrics, and scope changes as a timeline.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import Settings
from app.models.contracts import (
    GraphEdge,
    GraphNode,
    MemoryGraphResponse,
)

logger = logging.getLogger("voxquery.services.memory_graph")


async def generate_memory_graph(
    session_id: UUID,
    settings: Settings,
    turns: list[dict] | None = None,
) -> MemoryGraphResponse:
    """
    Construct analysis lineage dynamically from conversation turns.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    if turns:
        # Build dynamic DAG from session turns
        prev_q_id = None
        for idx, turn in enumerate(turns, start=1):
            q_id = f"node_q_{idx}"

            user_input = turn.get("user_input", f"Turn {idx} Query")
            metric_name = turn.get("metric_name") or turn.get("metric")
            source_tables = turn.get("source_tables") or []
            filter_predicates = turn.get("filter_predicates") or []

            nodes.append(GraphNode(id=q_id, label=user_input, type="query", turn_index=idx))

            metric_id = None
            if metric_name:
                metric_id = f"node_m_{idx}"
                nodes.append(GraphNode(id=metric_id, label=str(metric_name), type="metric", turn_index=idx))
                edges.append(GraphEdge(source=q_id, target=metric_id, relation="measures"))

            # Add source table entity nodes
            for table_idx, table_name in enumerate(source_tables, start=1):
                e_id = f"node_e_{idx}_{table_idx}"
                nodes.append(GraphNode(id=e_id, label=f"Entity: {table_name}", type="entity", turn_index=idx))
                edges.append(GraphEdge(source=q_id, target=e_id, relation="uses"))

            # Add filter predicate nodes
            for filter_idx, predicate in enumerate(filter_predicates, start=1):
                f_id = f"node_f_{idx}_{filter_idx}"
                nodes.append(GraphNode(id=f_id, label=f"Filter: {predicate}", type="filter", turn_index=idx))
                edges.append(GraphEdge(source=q_id, target=f_id, relation="applies"))
                if metric_id:
                    edges.append(GraphEdge(source=f_id, target=metric_id, relation="refines"))

            if prev_q_id:
                edges.append(GraphEdge(source=prev_q_id, target=q_id, relation="followed_by"))
            prev_q_id = q_id

    return MemoryGraphResponse(
        session_id=session_id,
        nodes=nodes,
        edges=edges,
    )
