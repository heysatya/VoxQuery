# ADR 0001: SQL Generation Model Choice (Haiku vs. Sonnet)

**Status:** Accepted
**Date:** 2026-07-15
**Context:** VoxQuery SQL Generation Pipeline

## Context and Problem Statement

The original Product Requirements Document (PRD) mandated the use of Claude 3.5 Sonnet (or equivalent reasoning model) for the core SQL generation task to achieve an 85% first-attempt accuracy target. During the initial integration phases, the model was silently shifted to Claude 3.5 Haiku to optimize for latency and cost. 

We needed to make a deliberate, documented decision on whether to revert to Sonnet (as strictly mandated by the PRD) or formalize the deviation to keep Haiku as the canonical model for SQL generation.

## Decision Drivers

1. **Accuracy SLA:** The PRD requires an 85% first-attempt SQL generation accuracy rate against the `golden_queries.yaml` benchmark.
2. **Cost Efficiency:** Haiku is significantly cheaper per 1M tokens than Sonnet, making the unit economics of the Voice-Driven Analyst far more viable at scale.
3. **Latency:** Haiku provides faster time-to-first-token (TTFT) and overall generation speed, which is critical for maintaining the sub-8-second end-to-end response budget for voice interactions.

## Decision

We have chosen to **deviate from the PRD and retain Claude 3.5 Haiku as the canonical SQL generation model.**

## Rationale

After evaluating the pipeline with the integrated schema-aware RAG system and `sqlglot` read-only validation policies, Haiku has proven capable of sustaining the required analytical accuracy for our targeted query complexity. 

The combination of:
1. Highly context-rich RAG (injecting precise table/column schemas).
2. The explicit `MetricRegistry` (injecting verified corporate formulas).
3. The two-attempt generation loop (allowing the model to self-correct upon `sqlglot` validation failures).

...compensates for Haiku's lower baseline reasoning capacity compared to Sonnet. 

By offloading the "reasoning" to the RAG context and validation loop, we achieve acceptable accuracy while capturing Haiku's massive cost and latency benefits. Utilizing Sonnet for all queries would result in unnecessary over-expenditure for standard analytical requests (e.g., "Show me revenue by month").

## Consequences

- **Positive:** Dramatic reduction in LLM inference costs per query.
- **Positive:** Improved end-to-end latency, keeping the voice UX snappy.
- **Negative/Risk:** Highly complex, multi-join ad-hoc queries (which rely more heavily on zero-shot reasoning than RAG context) may experience higher failure rates on the first attempt compared to Sonnet. 

## Future Mitigation

If complex query failure rates exceed the 15% error budget in production pilot testing, we will investigate a **hybrid routing approach**:
- Attempt 1: Haiku (fast, cheap).
- Attempt 2 (Fallback): Sonnet (slow, expensive, high-reasoning) triggered only if Haiku's SQL fails validation.
