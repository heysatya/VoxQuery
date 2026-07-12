"""
metric_registry.py
──────────────────
Loads and manages the business metric registry from YAML.

Design decisions:
- Metrics defined in YAML (version-controlled by data team)
- Loaded once at startup, cached in memory
- Fuzzy matching for synonym resolution
- Critical for preventing LLM metric hallucination
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from app.metadata.models import MetricDefinition

logger = logging.getLogger(__name__)


class MetricRegistry:
    """
    Central registry of certified business metric definitions.

    Usage:
        registry = MetricRegistry("data/metrics.yaml")
        metrics = registry.list_metrics()
        revenue = registry.find("revenue")
        matches = registry.search("total sales")
    """

    def __init__(self, metrics_path: str):
        self.metrics_path = Path(metrics_path)
        self._metrics: dict[str, MetricDefinition] = {}
        self._synonym_index: dict[str, str] = {}  # synonym -> metric name
        self.load()

    def load(self) -> None:
        """
        Load metrics from YAML file.
        Builds an in-memory index for fast lookup.
        """
        if not self.metrics_path.exists():
            logger.warning(
                "Metrics file not found at '%s'. "
                "Starting with empty registry.",
                self.metrics_path,
            )
            return

        with open(self.metrics_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or "metrics" not in raw:
            logger.warning("Metrics YAML has no 'metrics' key.")
            return

        loaded_count = 0
        for item in raw["metrics"]:
            try:
                metric = MetricDefinition(**item)
                self._metrics[metric.name] = metric

                # Build synonym index
                for synonym in metric.all_names:
                    self._synonym_index[synonym.lower()] = metric.name

                loaded_count += 1
            except Exception as e:
                logger.error("Failed to load metric '%s': %s",
                             item.get("name"), e)

        logger.info(
            "Loaded %d metrics from '%s'",
            loaded_count,
            self.metrics_path,
        )

    def find(self, name: str) -> Optional[MetricDefinition]:
        """
        Find a metric by exact name or synonym (case-insensitive).

        Args:
            name: Metric name or synonym

        Returns:
            MetricDefinition or None
        """
        # Try exact name first
        if name in self._metrics:
            return self._metrics[name]

        # Try synonym index
        canonical = self._synonym_index.get(name.lower())
        if canonical:
            return self._metrics.get(canonical)

        return None

    def search(self, query: str) -> list[MetricDefinition]:
        """
        Search metrics by partial name or synonym match.

        Args:
            query: Free-text search term

        Returns:
            List of matching MetricDefinitions (best match first)
        """
        query_lower = query.lower()
        exact_matches: list[MetricDefinition] = []
        partial_matches: list[MetricDefinition] = []

        for metric in self._metrics.values():
            all_names_lower = [n.lower() for n in metric.all_names]

            if query_lower in all_names_lower:
                exact_matches.append(metric)
            elif any(query_lower in n for n in all_names_lower):
                partial_matches.append(metric)
            elif query_lower in metric.description.lower():
                partial_matches.append(metric)

        return exact_matches + partial_matches

    def list_metrics(self) -> list[MetricDefinition]:
        """Return all registered metrics."""
        return list(self._metrics.values())

    def list_certified(self) -> list[MetricDefinition]:
        """Return only certified metrics."""
        return [m for m in self._metrics.values() if m.certified]

    @property
    def count(self) -> int:
        """Number of registered metrics."""
        return len(self._metrics)

    def get_all_synonyms(self) -> dict[str, str]:
        """Return the full synonym index (synonym → canonical name)."""
        return dict(self._synonym_index)

    def to_context_string(self) -> str:
        """
        Render all certified metrics as a context string for LLMs.
        """
        certified = self.list_certified()
        if not certified:
            return "No certified metrics defined."

        lines = ["Certified Business Metrics:"]
        for metric in certified:
            lines.append(f"\n{metric.to_metric_text()}")

        return "\n".join(lines)
