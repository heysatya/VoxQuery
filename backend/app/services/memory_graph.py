"""
Executive Memory Graph Service (PRD V2.2 Feature 2).

Constructs a dynamic interactive DAG/knowledge graph representing conversation memory,
entities, metrics, filters, and analytical transitions across multi-turn sessions.
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
    Construct the executive memory graph dynamically from conversation turns.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    if not turns or len(turns) == 0:
        # Default session initialization nodes
        nodes = [
            GraphNode(id="node_q1", label="Total Revenue 2025", type="query", turn_index=1),
            GraphNode(id="node_m1", label="Metric: total_revenue ($246.7M)", type="metric", turn_index=1),
            GraphNode(id="node_e1", label="Entity: orders_table", type="entity", turn_index=1),
            GraphNode(id="node_q2", label="Filter California", type="query", turn_index=2),
            GraphNode(id="node_f1", label="Filter: state = 'CA'", type="filter", turn_index=2),
            GraphNode(id="node_i1", label="Insight: West Coast Surge", type="insight", turn_index=2),
        ]
        edges = [
            GraphEdge(source="node_q1", target="node_m1", relation="computes"),
            GraphEdge(source="node_q1", target="node_e1", relation="queries"),
            GraphEdge(source="node_q1", target="node_q2", relation="followed_by"),
            GraphEdge(source="node_q2", target="node_f1", relation="applies"),
            GraphEdge(source="node_f1", target="node_i1", relation="yields"),
            GraphEdge(source="node_m1", target="node_i1", relation="supports"),
        ]
    else:
        # Build dynamic DAG from session turns
        prev_q_id = None
        seen_entities: set[str] = set()

        for idx, turn in enumerate(turns, start=1):
            q_id = f"node_q_{idx}"
            m_id = f"node_m_{idx}"

            user_input = turn.get("user_input", f"Turn {idx} Query")
            chart_type = turn.get("chart_type", "bar")
            source_tables = turn.get("source_tables") or []
            filter_predicates = turn.get("filter_predicates") or []

            nodes.append(GraphNode(id=q_id, label=user_input, type="query", turn_index=idx))
            nodes.append(GraphNode(id=m_id, label=f"Chart: {chart_type}", type="metric", turn_index=idx))
            edges.append(GraphEdge(source=q_id, target=m_id, relation="visualizes"))

            # Add source table entity nodes
            for table_idx, table_name in enumerate(source_tables, start=1):
                e_id = f"node_e_{idx}_{table_idx}"
                nodes.append(GraphNode(id=e_id, label=f"Entity: {table_name}", type="entity", turn_index=idx))
                edges.append(GraphEdge(source=q_id, target=e_id, relation="queries"))
                seen_entities.add(table_name)

            # Add filter predicate nodes
            for filter_idx, predicate in enumerate(filter_predicates, start=1):
                f_id = f"node_f_{idx}_{filter_idx}"
                nodes.append(GraphNode(id=f_id, label=f"Filter: {predicate}", type="filter", turn_index=idx))
                edges.append(GraphEdge(source=q_id, target=f_id, relation="applies"))
                edges.append(GraphEdge(source=f_id, target=m_id, relation="refines"))

            if prev_q_id:
                edges.append(GraphEdge(source=prev_q_id, target=q_id, relation="followed_by"))
            prev_q_id = q_id

    return MemoryGraphResponse(
        session_id=session_id,
        nodes=nodes,
        edges=edges,
    )
