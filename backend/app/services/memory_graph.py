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
        # Build DAG dynamically from turns
        prev_q_id = None
        for idx, turn in enumerate(turns, start=1):
            q_id = f"node_q_{idx}"
            m_id = f"node_m_{idx}"
            
            user_input = turn.get("user_input", f"Turn {idx} Query")
            chart_type = turn.get("chart_type", "bar")
            
            nodes.append(GraphNode(id=q_id, label=user_input, type="query", turn_index=idx))
            nodes.append(GraphNode(id=m_id, label=f"Chart: {chart_type}", type="metric", turn_index=idx))
            edges.append(GraphEdge(source=q_id, target=m_id, relation="visualizes"))

            if prev_q_id:
                edges.append(GraphEdge(source=prev_q_id, target=q_id, relation="followed_by"))
            prev_q_id = q_id

    return MemoryGraphResponse(
        session_id=session_id,
        nodes=nodes,
        edges=edges,
    )
