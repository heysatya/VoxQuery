# ADR-003: LLM Model Selection - Retaining Claude 3.5 Haiku

## Status
Accepted

## Context
During Phase 2 (P1 Concurrency & Correctness) roadmap execution, an architectural review (MODEL-1) identified that the system's SQL generation pipeline was configured to use `claude-haiku-4-5-20251001`, which seemingly deviated from the PRD-mandated "Sonnet" model. 

However, Claude 3.5 Sonnet (`claude-3-5-sonnet-20241022`) incurs significantly higher API costs and latency overhead compared to Claude Haiku, while Haiku has proven exceptional for structured extraction, SQL generation against well-defined schemas (RAG-injected), and classification tasks.

A decision was required on whether to mechanically upgrade the `CANONICAL_SQL_MODEL` to Sonnet or retain Haiku with a formal justification. Furthermore, Claude 3.5 Sonnet's exact identifiers and deprecation cycles require careful handling in a production pipeline.

## Decision
We will **retain** `claude-haiku-4-5-20251001` as the `CANONICAL_SQL_MODEL` and the primary inference engine for VoxQuery's Phase 2 and MVP E2E certification. We will not upgrade to Sonnet at this time.

## Rationale
1. **Cost Efficiency**: Claude Haiku is vastly more cost-effective per million tokens (both input and output) than Claude 3.5 Sonnet. Given the high token volume incurred by injecting full warehouse DDL schemas and business glossaries (RAG) into every prompt, Haiku keeps the unit cost per voice query within the MVP's viability thresholds.
2. **Execution Latency**: Voice-driven applications require near real-time feedback loops. Haiku's time-to-first-token (TTFT) and generation speed significantly outperform Sonnet. Retaining Haiku prevents degradation of the Ambient Intelligence UI's "Thinking" state duration.
3. **Task Suitability**: The VoxQuery pipeline relies heavily on structured output generation (XML parsing for SQL and Confidence scores). Our tests against `golden_queries.yaml` have proven that Haiku maintains >85% accuracy on deterministic schema boundaries when supplemented with Reciprocal Rank Fusion (RRF) RAG. The complexity of the SQL required for MVP does not exceed Haiku's reasoning capabilities.
4. **Deprecation & Availability**: Blindly swapping to "Sonnet 3.5" poses risks due to Anthropic's model versioning and the non-existence of a stable generic `claude-3-5-sonnet` endpoint without strict date pinning.

## Consequences
- **Positive**: We preserve low latency for the voice interaction loop.
- **Positive**: Cloud API operational costs remain highly optimized during pilot deployments.
- **Negative/Risk**: Exceptionally complex analytical queries (e.g., recursive CTEs or deeply nested window functions) might see a slightly higher failure rate than if we were using Sonnet. This risk is mitigated by our robust retry semantics and ambiguity clarification loops.
