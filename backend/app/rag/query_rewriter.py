"""
query_rewriter.py
─────────────────
Normalizes and expands user queries before retrieval.

Design decisions:
- Rule-based first (fast, no LLM cost, deterministic)
- Expands domain-specific synonyms from metric registry
- Resolves temporal references ("last quarter" → Q3 2024)
- Extracts entities for downstream metadata filtering
- LLM rewrite is optional and disabled by default in MVP
  (add it in Phase 4 for conversation memory)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.rag.glossary_defaults import (
    DEFAULT_METRIC_SYNONYMS,
    DEFAULT_TABLE_SYNONYMS,
    DEFAULT_METRIC_TO_TABLES,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────


@dataclass
class RewrittenQuery:
    """
    Output of the query rewriter.
    Contains the original query plus enriched signals.
    """
    original: str
    rewritten: str

    # Expanded terms for retrieval (synonyms, related concepts)
    expanded_terms: list[str] = field(default_factory=list)

    # Extracted entities
    entities: dict[str, str] = field(default_factory=dict)

    # Time context
    time_references: list[str] = field(default_factory=list)
    resolved_dates: dict[str, str] = field(default_factory=dict)

    # Domain signals
    detected_domain: Optional[str] = None
    detected_metrics: list[str] = field(default_factory=list)
    detected_tables: list[str] = field(default_factory=list)

    def get_retrieval_query(self) -> str:
        """
        Return the query string to use for retrieval.
        Includes original + expanded terms for maximum recall.
        """
        parts = [self.rewritten]
        if self.expanded_terms:
            parts.append(" ".join(self.expanded_terms))
        return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────
# Synonym Maps
# ─────────────────────────────────────────────────────────────────────


# Business term → canonical metric name mappings


# Time reference patterns → SQL-friendly descriptions
TIME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\blast\s+quarter\b", re.IGNORECASE), "last quarter"),
    (re.compile(r"\bthis\s+quarter\b", re.IGNORECASE), "current quarter"),
    (re.compile(r"\blast\s+month\b", re.IGNORECASE), "last month"),
    (re.compile(r"\bthis\s+month\b", re.IGNORECASE), "current month"),
    (re.compile(r"\blast\s+year\b", re.IGNORECASE), "last year"),
    (re.compile(r"\bthis\s+year\b", re.IGNORECASE), "current year"),
    (re.compile(r"\byesterday\b", re.IGNORECASE), "yesterday"),
    (re.compile(r"\btoday\b", re.IGNORECASE), "today"),
    (re.compile(r"\blast\s+(\d+)\s+days?\b", re.IGNORECASE), "last N days"),
    (re.compile(r"\bq[1-4]\s*\d{4}\b", re.IGNORECASE), "specific quarter"),
    (re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
                re.IGNORECASE), "month name"),
]

# Domain keyword → domain name
DOMAIN_SIGNALS: dict[str, str] = {
    "revenue":    "sales",
    "sales":      "sales",
    "orders":     "sales",
    "customer":   "customers",
    "churn":      "customers",
    "retention":  "customers",
    "product":    "products",
    "margin":     "products",
    "seller":     "sellers",
    "vendor":     "sellers",
    "delivery":   "operations",
    "shipping":   "operations",
    "payment":    "payments",
    "review":     "reviews",
    "rating":     "reviews",
    "geographic": "geography",
    "region":     "geography",
    "state":      "geography",
}


# ─────────────────────────────────────────────────────────────────────
# Query Rewriter
# ─────────────────────────────────────────────────────────────────────


class QueryRewriter:
    """
    Rule-based query rewriter that enriches queries before retrieval.

    What it does:
    1. Normalizes whitespace and casing
    2. Expands business synonyms (revenue → sales, net sales, topline)
    3. Detects metric references from query text
    4. Detects table references
    5. Extracts time references for context
    6. Infers business domain

    What it does NOT do (MVP):
    - LLM-based coreference resolution (Phase 4)
    - Conversation history integration (Phase 4)

    Usage:
        rewriter = QueryRewriter()
        result = rewriter.rewrite("What was our revenue last quarter?")
        print(result.rewritten)         # "What was our revenue last quarter?"
        print(result.expanded_terms)    # ["sales", "net sales", "orders", ...]
        print(result.detected_metrics)  # ["revenue"]
    """

    def __init__(
        self,
        metric_synonyms: Optional[dict[str, list[str]]] = None,
        table_synonyms: Optional[dict[str, list[str]]] = None,
    ):
        self.metric_synonyms = metric_synonyms or DEFAULT_METRIC_SYNONYMS
        self.table_synonyms = table_synonyms or DEFAULT_TABLE_SYNONYMS

        # Build reverse lookup: synonym → canonical metric name
        self._metric_lookup: dict[str, str] = {}
        for canonical, synonyms in self.metric_synonyms.items():
            for syn in synonyms:
                self._metric_lookup[syn.lower()] = canonical

        # Build reverse lookup: term → table name
        self._table_lookup: dict[str, str] = {}
        for table, terms in self.table_synonyms.items():
            for term in terms:
                self._table_lookup[term.lower()] = table

    def rewrite(self, query: str) -> RewrittenQuery:
        """
        Rewrite and enrich a user query.

        Args:
            query: Raw user query string

        Returns:
            RewrittenQuery with all enrichment signals
        """
        if not query or not query.strip():
            return RewrittenQuery(original=query, rewritten=query)

        # Normalize
        normalized = self._normalize(query)

        # Detect entities
        detected_metrics = self._detect_metrics(normalized)
        detected_tables = self._detect_tables(normalized)
        time_references = self._detect_time_references(normalized)
        domain = self._detect_domain(normalized)

        # Expand terms for retrieval
        expanded = self._expand_terms(normalized, detected_metrics, detected_tables)

        result = RewrittenQuery(
            original=query,
            rewritten=normalized,
            expanded_terms=expanded,
            time_references=time_references,
            detected_domain=domain,
            detected_metrics=detected_metrics,
            detected_tables=detected_tables,
        )

        logger.debug(
            "Rewritten query: '%s' → metrics=%s, tables=%s, domain=%s",
            query[:50],
            detected_metrics,
            detected_tables,
            domain,
        )
        return result

    def _normalize(self, query: str) -> str:
        """Basic text normalization."""
        # Strip leading/trailing whitespace
        normalized = query.strip()
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def _detect_metrics(self, query: str) -> list[str]:
        """
        Identify metric names mentioned in the query.

        Returns:
            List of canonical metric names found
        """
        query_lower = query.lower()
        found = []
        for synonym, canonical in self._metric_lookup.items():
            if synonym in query_lower and canonical not in found:
                found.append(canonical)
        return found

    def _detect_tables(self, query: str) -> list[str]:
        """
        Identify table names mentioned or implied in the query.

        Returns:
            List of table names (uppercase)
        """
        query_lower = query.lower()
        found = []
        for term, table in self._table_lookup.items():
            if term in query_lower and table not in found:
                found.append(table)
        return found

    def _detect_time_references(self, query: str) -> list[str]:
        """Extract temporal references from the query."""
        references = []
        for pattern, label in TIME_PATTERNS:
            if pattern.search(query):
                references.append(label)
        return references

    def _detect_domain(self, query: str) -> Optional[str]:
        """Infer the primary business domain from the query."""
        query_lower = query.lower()
        domain_scores: dict[str, int] = {}

        for keyword, domain in DOMAIN_SIGNALS.items():
            if keyword in query_lower:
                domain_scores[domain] = domain_scores.get(domain, 0) + 1

        if not domain_scores:
            return None

        return max(domain_scores, key=lambda d: domain_scores[d])

    def _expand_terms(
        self,
        query: str,
        detected_metrics: list[str],
        detected_tables: list[str],
    ) -> list[str]:
        """
        Expand the query with synonyms for detected metrics and tables.
        These expanded terms are appended to the retrieval query
        to boost recall without changing the original query.
        """
        expanded = set()

        # Add synonyms and canonical names for detected metrics
        for metric in detected_metrics:
            expanded.add(metric)
            synonyms = self.metric_synonyms.get(metric, [])
            expanded.update(synonyms)

        # Add canonical names and synonyms for detected tables
        
        # Also include tables related to detected metrics
        tables_to_expand = set(detected_tables)
        for metric in detected_metrics:
            tables_to_expand.update(DEFAULT_METRIC_TO_TABLES.get(metric, []))
            
        for table in tables_to_expand:
            expanded.add(table)
            synonyms = self.table_synonyms.get(table, [])
            expanded.update(synonyms)

        # Remove terms already in the query to avoid redundancy
        query_lower = query.lower()
        expanded = {
            term for term in expanded
            if term.lower() not in query_lower
        }

        return sorted(expanded)
