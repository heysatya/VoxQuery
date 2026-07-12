from __future__ import annotations

from app.metadata.models import TableMeta


def enrich_table(table: TableMeta, sample_rows: list[dict]) -> TableMeta:
    """Attach sample values from *sample_rows* to each column."""
    for col in table.columns:
        values = [
            str(row[col.name])
            for row in sample_rows
            if col.name in row and row[col.name] is not None
        ]
        col.sample_values = values[:5]
    return table
