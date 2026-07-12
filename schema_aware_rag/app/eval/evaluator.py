"""
evaluator.py
─────────────
Evaluation harness for the Schema-Aware RAG layer.

Measures:
  - Recall@K (primary metric): Are expected chunks in top-K?
  - Latency: P50, P95, P99 across all queries
  - Coverage: Which chunk types are well-retrieved?

Design decisions:
- YAML golden dataset (human-curated, version-controlled)
- Soft matching: keyword presence in chunk text (not exact ID match)
- Per-query breakdown for targeted improvement
- Report printed to console + optionally saved as JSON
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from app.metadata.metric_registry import MetricRegistry
from app.metadata.models import ChunkType, RetrievedChunk
from app.retrieval.context_builder import ContextBuilder
from app.retrieval.hybrid_retriever import HybridRetriever, RetrievalConfig
from app.retrieval.query_rewriter import QueryRewriter

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ExpectedChunk:
    """A chunk the retriever is expected to return."""
    chunk_type: str     # "metric", "table", "rule"
    identifier: str     # metric name, table name, or rule keyword


@dataclass
class QueryEvalResult:
    """Evaluation result for a single query."""
    query_id: str
    question: str
    domain: str
    complexity: str

    expected: list[ExpectedChunk]
    retrieved_chunks: list[RetrievedChunk]

    # Recall metrics
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    hits_at_5: int = 0
    hits_at_10: int = 0
    total_expected: int = 0

    # Thresholds from golden set
    min_recall_at_5: float = 0.80
    min_recall_at_10: float = 0.90

    # Performance
    latency_ms: float = 0.0

    # Pass/fail
    passed_at_5: bool = False
    passed_at_10: bool = False

    # Missed chunks (for debugging)
    missed_at_10: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """Full evaluation report across all queries."""
    total_queries: int = 0
    passed_at_5: int = 0
    passed_at_10: int = 0

    avg_recall_at_5: float = 0.0
    avg_recall_at_10: float = 0.0

    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0

    by_domain: dict[str, dict] = field(default_factory=dict)
    by_complexity: dict[str, dict] = field(default_factory=dict)

    query_results: list[QueryEvalResult] = field(default_factory=list)

    # Target thresholds
    TARGET_RECALL_AT_5 = 0.85
    TARGET_RECALL_AT_10 = 0.90

    @property
    def pass_rate_at_5(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.passed_at_5 / self.total_queries

    @property
    def pass_rate_at_10(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.passed_at_10 / self.total_queries

    @property
    def meets_recall_target(self) -> bool:
        return self.avg_recall_at_10 >= self.TARGET_RECALL_AT_10


# ─────────────────────────────────────────────────────────────────────
# Evaluator
# ─────────────────────────────────────────────────────────────────────


class RAGEvaluator:
    """
    Evaluates the Schema-Aware RAG layer against a golden dataset.

    Usage:
        evaluator = RAGEvaluator(golden_queries_path="app/eval/golden_queries.yaml")
        evaluator.setup()
        report = evaluator.run()
        evaluator.print_report(report)
    """

    def __init__(
        self,
        golden_queries_path: str = "app/eval/golden_queries.yaml",
        retriever: Optional[HybridRetriever] = None,
        top_k: int = 10,
    ):
        self.golden_queries_path = Path(golden_queries_path)
        self._retriever = retriever
        self.top_k = top_k

    def setup(self) -> None:
        """Initialize retriever if not provided."""
        if self._retriever is None:
            logger.info("Initializing retriever for evaluation...")
            self._retriever = HybridRetriever()
            self._retriever.load_indexes()

    def _load_golden_queries(self) -> list[dict]:
        """Load and parse the golden query dataset."""
        if not self.golden_queries_path.exists():
            raise FileNotFoundError(
                f"Golden queries file not found: {self.golden_queries_path}"
            )

        with open(self.golden_queries_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        queries = raw.get("queries", [])
        logger.info("Loaded %d golden queries", len(queries))
        return queries

    def _parse_expected_chunks(self, expected_raw: list[dict]) -> list[ExpectedChunk]:
        """Parse expected chunk specs from YAML."""
        chunks = []
        for item in expected_raw:
            if "metric" in item:
                chunks.append(ExpectedChunk("metric", item["metric"]))
            elif "table" in item:
                chunks.append(ExpectedChunk("table", item["table"]))
            elif "rule" in item:
                chunks.append(ExpectedChunk("rule", item["rule"]))
        return chunks

    def _chunk_matches_expected(
        self,
        retrieved: RetrievedChunk,
        expected: ExpectedChunk,
    ) -> bool:
        """
        Check if a retrieved chunk satisfies an expected chunk requirement.

        Matching strategy (soft matching):
        - metric: chunk_type == METRIC_CARD and metric name in text
        - table: chunk_type == TABLE_CARD and table name in text
        - rule: chunk_type == BUSINESS_RULE and keyword in text

        Uses case-insensitive substring matching to be robust against
        formatting differences.
        """
        chunk = retrieved.chunk
        text_lower = chunk.text.lower()
        identifier_lower = expected.identifier.lower()

        if expected.chunk_type == "metric":
            return (
                chunk.chunk_type == ChunkType.METRIC_CARD
                and (
                    identifier_lower in text_lower
                    or (chunk.metadata.metric or "").lower() == identifier_lower
                )
            )
        elif expected.chunk_type == "table":
            return (
                chunk.chunk_type == ChunkType.TABLE_CARD
                and (
                    identifier_lower in text_lower
                    or (chunk.source_table or "").lower().endswith(identifier_lower.lower())
                )
            )
        elif expected.chunk_type == "rule":
            return (
                chunk.chunk_type == ChunkType.BUSINESS_RULE
                and identifier_lower in text_lower
            )
        return False

    def _evaluate_query(
        self,
        query_spec: dict,
        retrieved_chunks: list[RetrievedChunk],
        latency_ms: float,
    ) -> QueryEvalResult:
        """Evaluate a single query against expected chunks."""
        expected = self._parse_expected_chunks(
            query_spec.get("expected_chunks", [])
        )

        result = QueryEvalResult(
            query_id=query_spec.get("id", "unknown"),
            question=query_spec["question"],
            domain=query_spec.get("domain", "unknown"),
            complexity=query_spec.get("complexity", "unknown"),
            expected=expected,
            retrieved_chunks=retrieved_chunks,
            total_expected=len(expected),
            latency_ms=latency_ms,
            min_recall_at_5=query_spec.get("min_recall_at_5", 0.80),
            min_recall_at_10=query_spec.get("min_recall_at_10", 0.90),
        )

        if not expected:
            result.recall_at_5 = 1.0
            result.recall_at_10 = 1.0
            result.passed_at_5 = True
            result.passed_at_10 = True
            return result

        # Compute hits at K
        top_5 = retrieved_chunks[:5]
        top_10 = retrieved_chunks[:10]

        hits_5 = set()
        hits_10 = set()
        missed = []

        for i, exp in enumerate(expected):
            found_at_5 = any(self._chunk_matches_expected(r, exp)
                             for r in top_5)
            found_at_10 = any(self._chunk_matches_expected(r, exp)
                              for r in top_10)

            if found_at_5:
                hits_5.add(i)
            if found_at_10:
                hits_10.add(i)
            else:
                missed.append(f"{exp.chunk_type}:{exp.identifier}")

        result.hits_at_5 = len(hits_5)
        result.hits_at_10 = len(hits_10)
        result.recall_at_5 = len(hits_5) / len(expected)
        result.recall_at_10 = len(hits_10) / len(expected)
        result.missed_at_10 = missed

        result.passed_at_5 = result.recall_at_5 >= result.min_recall_at_5
        result.passed_at_10 = result.recall_at_10 >= result.min_recall_at_10

        return result

    def run(
        self,
        query_ids: Optional[list[str]] = None,
    ) -> EvalReport:
        """
        Run the full evaluation suite.

        Args:
            query_ids: Optional list of query IDs to run (runs all if None)

        Returns:
            EvalReport with comprehensive metrics
        """
        if self._retriever is None:
            self.setup()

        golden_queries = self._load_golden_queries()

        # Filter to specific query IDs if requested
        if query_ids:
            golden_queries = [
                q for q in golden_queries
                if q.get("id") in query_ids
            ]
            logger.info("Running subset: %d queries", len(golden_queries))

        query_results: list[QueryEvalResult] = []
        latencies: list[float] = []

        logger.info("=" * 60)
        logger.info("RUNNING EVALUATION: %d queries", len(golden_queries))
        logger.info("=" * 60)

        for i, query_spec in enumerate(golden_queries):
            question = query_spec["question"]
            query_id = query_spec.get("id", f"q_{i}")

            logger.debug("Evaluating [%d/%d]: %s", i + 1,
                         len(golden_queries), question[:50])

            # Time the retrieval
            t_start = time.time()
            try:
                retrieval_result = self._retriever.retrieve(
                    query=question,
                    top_k=self.top_k,
                )
                retrieved_chunks = retrieval_result.chunks
                actual_latency = (time.time() - t_start) * 1000
            except Exception as e:
                logger.error("Retrieval failed for '%s': %s", question[:50], e)
                actual_latency = (time.time() - t_start) * 1000
                retrieved_chunks = []

            latencies.append(actual_latency)

            # Evaluate
            eval_result = self._evaluate_query(
                query_spec=query_spec,
                retrieved_chunks=retrieved_chunks,
                latency_ms=actual_latency,
            )
            query_results.append(eval_result)

            # Log per-query result
            status = "✅" if eval_result.passed_at_10 else "❌"
            logger.info(
                "%s [%s] R@5=%.2f R@10=%.2f | %.1fms | %s",
                status,
                query_id,
                eval_result.recall_at_5,
                eval_result.recall_at_10,
                actual_latency,
                question[:45],
            )
            if eval_result.missed_at_10:
                logger.debug("  Missed: %s", eval_result.missed_at_10)

        # Aggregate report
        report = self._aggregate_report(query_results, latencies)
        return report

    def _aggregate_report(
        self,
        query_results: list[QueryEvalResult],
        latencies: list[float],
    ) -> EvalReport:
        """Aggregate per-query results into a report."""
        import statistics

        report = EvalReport(
            total_queries=len(query_results),
            query_results=query_results,
        )

        if not query_results:
            return report

        # Core metrics
        report.passed_at_5 = sum(1 for r in query_results if r.passed_at_5)
        report.passed_at_10 = sum(1 for r in query_results if r.passed_at_10)
        report.avg_recall_at_5 = statistics.mean(
            r.recall_at_5 for r in query_results)
        report.avg_recall_at_10 = statistics.mean(
            r.recall_at_10 for r in query_results)

        # Latency percentiles
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)
        report.latency_p50_ms = sorted_latencies[int(n * 0.50)]
        report.latency_p95_ms = sorted_latencies[int(n * 0.95)]
        report.latency_p99_ms = sorted_latencies[min(int(n * 0.99), n - 1)]

        # By domain
        domains: dict[str, list[QueryEvalResult]] = {}
        for r in query_results:
            domains.setdefault(r.domain, []).append(r)

        for domain, results in domains.items():
            report.by_domain[domain] = {
                "count": len(results),
                "avg_recall_at_10": statistics.mean(r.recall_at_10 for r in results),
                "pass_rate": sum(1 for r in results if r.passed_at_10) / len(results),
            }

        # By complexity
        complexities: dict[str, list[QueryEvalResult]] = {}
        for r in query_results:
            complexities.setdefault(r.complexity, []).append(r)

        for complexity, results in complexities.items():
            report.by_complexity[complexity] = {
                "count": len(results),
                "avg_recall_at_10": statistics.mean(r.recall_at_10 for r in results),
                "pass_rate": sum(1 for r in results if r.passed_at_10) / len(results),
            }

        return report

    def print_report(self, report: EvalReport) -> None:
        """Print a formatted evaluation report to console."""
        status = "✅ PASS" if report.meets_recall_target else "❌ FAIL"

        print("\n" + "=" * 65)
        print("SCHEMA-AWARE RAG EVALUATION REPORT")
        print("=" * 65)
        print(f"Status:              {status}")
        print(f"Total Queries:       {report.total_queries}")
        print()
        print("RECALL METRICS:")
        print(f"  Avg Recall@5:      {report.avg_recall_at_5:.1%}  "
              f"(target: >85%)")
        print(f"  Avg Recall@10:     {report.avg_recall_at_10:.1%}  "
              f"(target: >{EvalReport.TARGET_RECALL_AT_10:.0%})")
        print(f"  Pass Rate @5:      {report.pass_rate_at_5:.1%}  "
              f"({report.passed_at_5}/{report.total_queries})")
        print(f"  Pass Rate @10:     {report.pass_rate_at_10:.1%}  "
              f"({report.passed_at_10}/{report.total_queries})")
        print()
        print("LATENCY:")
        print(f"  P50:               {report.latency_p50_ms:.1f}ms  "
              f"(target: <300ms)")
        print(f"  P95:               {report.latency_p95_ms:.1f}ms")
        print(f"  P99:               {report.latency_p99_ms:.1f}ms")
        print()

        print("BY DOMAIN:")
        for domain, stats in sorted(report.by_domain.items()):
            recall = stats["avg_recall_at_10"]
            mark = "✅" if recall >= 0.80 else "⚠️ " if recall >= 0.65 else "❌"
            print(f"  {mark} {domain:<20} R@10={recall:.1%}  "
                  f"({stats['count']} queries)")

        print()
        print("BY COMPLEXITY:")
        for complexity, stats in sorted(report.by_complexity.items()):
            recall = stats["avg_recall_at_10"]
            mark = "✅" if recall >= 0.80 else "⚠️ " if recall >= 0.65 else "❌"
            print(f"  {mark} {complexity:<20} R@10={recall:.1%}  "
                  f"({stats['count']} queries)")

        # Failed queries
        failed = [r for r in report.query_results if not r.passed_at_10]
        if failed:
            print()
            print(f"FAILED QUERIES ({len(failed)}/{report.total_queries}):")
            for r in failed:
                print(
                    f"  ❌ [{r.query_id}] R@10={r.recall_at_10:.1%} | {r.question[:55]}")
                if r.missed_at_10:
                    print(f"      Missed: {', '.join(r.missed_at_10)}")

        print("=" * 65)

    def save_report(self, report: EvalReport, output_path: str) -> None:
        """Save report as JSON for CI/CD integration."""
        output = {
            "summary": {
                "total_queries": report.total_queries,
                "passed_at_5": report.passed_at_5,
                "passed_at_10": report.passed_at_10,
                "avg_recall_at_5": round(report.avg_recall_at_5, 4),
                "avg_recall_at_10": round(report.avg_recall_at_10, 4),
                "latency_p50_ms": round(report.latency_p50_ms, 2),
                "latency_p95_ms": round(report.latency_p95_ms, 2),
                "latency_p99_ms": round(report.latency_p99_ms, 2),
                "meets_target": report.meets_recall_target,
            },
            "by_domain": report.by_domain,
            "by_complexity": report.by_complexity,
            "query_results": [
                {
                    "id": r.query_id,
                    "question": r.question,
                    "domain": r.domain,
                    "complexity": r.complexity,
                    "recall_at_5": round(r.recall_at_5, 4),
                    "recall_at_10": round(r.recall_at_10, 4),
                    "passed_at_5": r.passed_at_5,
                    "passed_at_10": r.passed_at_10,
                    "latency_ms": round(r.latency_ms, 2),
                    "missed_at_10": r.missed_at_10,
                }
                for r in report.query_results
            ],
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        logger.info("Report saved to: %s", output_path)


# ─────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────


def run_evaluation(
    golden_path: str = "app/eval/golden_queries.yaml",
    output_path: Optional[str] = None,
    query_ids: Optional[list[str]] = None,
) -> EvalReport:
    """Run the evaluation and optionally save results."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    evaluator = RAGEvaluator(golden_queries_path=golden_path)
    evaluator.setup()

    report = evaluator.run(query_ids=query_ids)
    evaluator.print_report(report)

    if output_path:
        evaluator.save_report(report, output_path)

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Evaluate Schema-Aware RAG Layer")
    parser.add_argument("--golden", default="app/eval/golden_queries.yaml")
    parser.add_argument("--output", default="data/eval_report.json")
    parser.add_argument("--query-ids", nargs="+", default=None)
    args = parser.parse_args()

    report = run_evaluation(
        golden_path=args.golden,
        output_path=args.output,
        query_ids=args.query_ids,
    )
    exit(0 if report.meets_recall_target else 1)
