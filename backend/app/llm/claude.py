import json
import logging
import re
from typing import Any

import anthropic
import sqlglot
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.llm.adapter import LlmAdapter, SqlGenerationResult, Storyteller
from app.models.contracts import ResultShape, SchemaChunk, SessionHistoryTurn, ApiError, ErrorCode
from langfuse import observe, get_client

logger = logging.getLogger(__name__)


def extract_sql_and_confidence(response_text: str) -> tuple[str, float | None]:
    """Extract clean SQL and self-confidence float from raw LLM text response.
    
    Handles XML tags (<sql>, <confidence>), unclosed tags, and markdown code fences
    (e.g. ```xml, ```sql, ```) in any order or combination.
    """
    text = response_text.strip()

    # 1. Extract confidence if present
    llm_self_confidence = None
    confidence_match = re.search(r"<confidence>\s*([0-9\.]+)\s*</confidence>", text, flags=re.IGNORECASE | re.DOTALL)
    if confidence_match:
        try:
            llm_self_confidence = float(confidence_match.group(1).strip())
        except ValueError:
            pass

    # Remove confidence block before SQL extraction
    text_no_conf = re.sub(r"<confidence>.*?</confidence>", "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    # 2. Extract SQL portion
    sql_match = re.search(r"<sql>(.*?)</sql>", text_no_conf, flags=re.IGNORECASE | re.DOTALL)
    if sql_match:
        raw_sql = sql_match.group(1).strip()
    else:
        unclosed_match = re.search(r"<sql>(.*)", text_no_conf, flags=re.IGNORECASE | re.DOTALL)
        if unclosed_match:
            raw_sql = unclosed_match.group(1).strip()
        else:
            raw_sql = text_no_conf

    # 3. Strip code fences and tags
    raw_sql = re.sub(r"^```[a-zA-Z]*\n?", "", raw_sql.strip())
    raw_sql = re.sub(r"\n?```$", "", raw_sql.strip())

    lines = raw_sql.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower() in ("<sql>", "</sql>", "```", "```sql", "```xml"):
            continue
        cleaned_lines.append(line)

    sql = "\n".join(cleaned_lines).strip()
    sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql)
    sql = re.sub(r"\n?```$", "", sql).strip()

    return sql, llm_self_confidence


def _safe_update_current_generation(**kwargs: Any) -> None:
    try:
        get_client().update_current_generation(**kwargs)
    except Exception as exc:
        logger.warning("Langfuse generation update skipped: %s", type(exc).__name__)


class ClaudeAdapter(LlmAdapter):
    def __init__(self, client: AsyncAnthropic) -> None:
        self.client = client
        self.model_name = get_settings().canonical_sql_model

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def generate_sql(
        self, 
        submitted_text: str, 
        schema_chunks: list[SchemaChunk],
        conversation_history: list[SessionHistoryTurn],
        *, 
        resolved_entities: dict[str, Any] | None = None, 
        feedback: str | None = None,
        previous_sql: str | None = None,
    ) -> SqlGenerationResult:
        _safe_update_current_generation(
            name="claude-sql-generation",
            input={
                "submitted_text": submitted_text,
                "resolved_entities": [
                    v.model_dump(mode="json") for v in (resolved_entities or {}).values()
                ],
                "feedback": feedback,
                "previous_sql": previous_sql,
            },
            model=self.model_name
        )

        schema_context = "\n".join([f"- {c.source_ref}: {c.content}" for c in schema_chunks])
        history_context = "\n".join([f"User: {t.user_query}\nSQL: {t.generated_sql}" for t in conversation_history])
        
        system_prompt = """You are an expert Snowflake SQL generator. Generate a read-only SQL query for the following request.
Always LIMIT to 10000 rows maximum.
IMPORTANT DIALECT & TYPE RULES:
1. Relative Date Filters: DO NOT use `CURRENT_DATE()`. Query relative to the max date in target table (e.g. `WHERE date_col >= DATEADD(day, -30, (SELECT MAX(date_col) FROM table_name))`).
2. Date/Time Functions: `DATE_TRUNC`, `DATEADD`, and `DATEDIFF` require TIMESTAMP/DATE types. If a column is stored as VARCHAR/string, explicitly cast with `TRY_TO_TIMESTAMP(col)` (e.g., `DATE_TRUNC('month', TRY_TO_TIMESTAMP(date_col))`).
3. Safe Division: Always use `DIV0(numerator, denominator)` when dividing to prevent division by zero runtime errors.
4. Case-Insensitive Matching: Use `ILIKE` or `LOWER(col) = LOWER('val')` for string filters.
5. Numeric Operations: If aggregating numerical values stored in VARCHAR fields, wrap with `TRY_TO_DOUBLE(col)` or `TRY_TO_NUMBER(col)`.
Return your output exactly in the following XML format:
<sql>
your valid SQL query here
</sql>
<confidence>
0.95
</confidence>"""

        user_prompt = f"""Schema Context:
{schema_context}

Conversation History:
{history_context}

Request: {submitted_text}"""
        
        if resolved_entities:
            entities_str = ", ".join([f"{k} = {v.resolution}" for k, v in resolved_entities.items()])
            user_prompt += f"\n\nNote: The user clarified the following entities: {entities_str}"
            
        if previous_sql:
            user_prompt += f"\n\nPrevious SQL attempt: {previous_sql}"
        if feedback:
            user_prompt += f"\n\nFeedback/Error from previous attempt (FIX THIS): {feedback}"

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
        except anthropic.AnthropicError as e:
            logger.error(f"LLM Generation failed: {e}")
            raise ApiError(ErrorCode.llm_unavailable, status_code=503) from e

        response_text = response.content[0].text.strip()
        sql, llm_self_confidence = extract_sql_and_confidence(response_text)

        # Validate with sqlglot
        validation_passed = True
        validation_error = None
        try:
            # Parse as snowflake dialect
            parsed = sqlglot.parse_one(sql, read="snowflake")
            
            # Simple check for read-only
            if not isinstance(parsed, sqlglot.exp.Select):
                validation_passed = False
                validation_error = "Generated SQL is not a SELECT statement."
                
        except Exception as e:
            logger.warning(f"SQL validation failed: {e}")
            validation_passed = False
            validation_error = f"SQL parsing failed: {e}"

        result = SqlGenerationResult(
            sql=sql,
            validation_passed=validation_passed,
            llm_self_confidence=llm_self_confidence,
            validation_error=validation_error
        )
        _safe_update_current_generation(output={"sql": result.sql, "confidence": result.llm_self_confidence, "validation_passed": validation_passed})
        return result

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def generate_clarification(self, dominant_signal: Any, user_input: str = "") -> tuple[str, list[str]]:
        signal_name = getattr(dominant_signal, "name", str(dominant_signal))
        _safe_update_current_generation(
            name="claude-clarification-generation",
            input={"dominant_signal": signal_name, "user_input": user_input},
            model=self.model_name
        )
        
        ambiguity_descriptions = {
            "entity_ambiguity": "It's unclear which specific customer, product, region, or business entity they are referring to.",
            "metric_ambiguity": "They asked for a metric (e.g., revenue, sales, active users) but it's not clear exactly which specific definition or formula to use.",
            "missing_join_path": "The requested data spans multiple domains, and it's unclear how they should be related or filtered.",
            "pronoun_reference_failure": "They used a pronoun (e.g., 'it', 'that', 'those') but it's unclear what it refers to in this context.",
            "temporal_ambiguity": "They asked about a time period (e.g., 'recent', 'last quarter') but the exact date range is unclear.",
            "scope_ambiguity": "The request is too broad or vaguely worded to translate into a precise data query."
        }
        
        description = ambiguity_descriptions.get(signal_name, signal_name.replace("_", " "))
        
        system_prompt = """You are an expert Data Analyst AI. The user just asked a data question, but the request was ambiguous.
Generate a polite, helpful clarification question to ask the user to resolve this ambiguity.
Provide 2 to 4 distinct, actionable options for them to choose from. Make the options human-readable and specific (e.g. "Total Gross Revenue" instead of "metric_1").
Always include a "Skip" option as the last option.

Respond ONLY with a valid JSON object matching this schema:
{
    "question": "The polite clarification question to ask the user",
    "options": ["Option 1", "Option 2", ..., "Skip"]
}"""

        user_prompt = f"""User's question: "{user_input}"

Specifically, the ambiguity is: {description}"""

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=300,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
        except anthropic.AnthropicError as e:
            logger.error(f"LLM Clarification failed: {e}")
            raise ApiError(ErrorCode.llm_unavailable, status_code=503) from e
        
        content = response.content[0].text.strip()
        
        try:
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            data = json.loads(content)
            question = data.get("question", f"Could you clarify regarding {dominant_signal}?")
            options = data.get("options", ["Option A", "Option B", "Skip"])
            _safe_update_current_generation(output={"question": question, "options": options})
            return question, options
        except Exception as e:
            logger.error(f"Failed to parse clarification JSON: {e}")
            question = f"Could you clarify regarding {dominant_signal}?"
            options = ["Option A", "Option B", "Skip"]
            _safe_update_current_generation(output={"question": question, "options": options, "error": str(e)})
            return question, options


class ClaudeStoryteller(Storyteller):
    def __init__(self, client: AsyncAnthropic) -> None:
        self.client = client
        self.model_name = get_settings().canonical_sql_model

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def summarize(self, result_shape: ResultShape, user_query: str) -> str:
        _safe_update_current_generation(
            name="claude-story-summarization",
            input={"user_query": user_query, "result_shape": result_shape.model_dump(mode="json")},
            model=self.model_name
        )
        system_prompt = """You are an expert Data Storyteller. Based on the user's query and the resulting data shape below, generate a STRICT 1-3 sentence narrative.
If the data reveals a significant trend, spike, or drop, you MUST explicitly highlight this anomaly and concisely state what drove the change (anomaly narration).
The narrative MUST follow this structure: Headline, Driver, Implication. 
DO NOT EXCEED 3 SENTENCES.
CRITICAL: Output PLAIN TEXT ONLY. Do not use ANY markdown formatting (no asterisks, no bolding, no bullet points). This text will be passed directly to a Text-to-Speech engine."""

        user_prompt = f"""User Query: {user_query}
Data Shape Summary: {result_shape.aggregate_summary}
Row Count: {result_shape.row_count}
Chart Type: {result_shape.chart_type}"""

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=300,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
        except anthropic.AnthropicError as e:
            logger.error(f"LLM Summarization failed: {e}")
            raise ApiError(ErrorCode.llm_unavailable, status_code=503) from e
        
        summary = response.content[0].text.strip()
        summary = summary.replace("*", "").replace("#", "")
        
        # Ensure it's not overly verbose by simple truncation if the LLM hallucinates longer text
        # But we trust the LLM mostly with this strong prompt.
        _safe_update_current_generation(output={"summary": summary})
        return summary

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def generate_proactive_questions(self, result_shape: ResultShape, user_query: str) -> list[str]:
        _safe_update_current_generation(
            name="claude-proactive-questions",
            input={"user_query": user_query, "result_shape": result_shape.model_dump(mode="json")},
            model=self.model_name
        )
        system_prompt = """You are an expert Data Analyst. Based on the user's original query and the resulting data shape below, suggest exactly 3 proactive follow-up questions that the user might want to ask next.
These questions should dive deeper into the data, explore anomalies, or break down the results by available dimensions.
Return ONLY a valid JSON array of 3 strings. Example: ["What is the breakdown by region?", "Are there any seasonal trends?"]"""
        
        user_prompt = f"""User Query: {user_query}
Data Shape Summary: {result_shape.aggregate_summary}
Row Count: {result_shape.row_count}
Chart Type: {result_shape.chart_type}"""

        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=200,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
        except Exception as e:
            logger.error(f"LLM Proactive questions failed: {e}")
            return [
                "What are the key drivers behind this?",
                "How does this compare to the previous period?",
                "Can we break this down by dimension?",
            ]
            
        content = response.content[0].text.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        try:
            questions = json.loads(content)
            if not isinstance(questions, list) or not questions:
                return [
                    "What are the key drivers behind this?",
                    "How does this compare to the previous period?",
                    "Can we break this down by dimension?",
                ]
            _safe_update_current_generation(output={"proactive_questions": questions[:3]})
            return [str(q) for q in questions[:3]]
        except Exception as e:
            logger.error(f"Failed to parse proactive questions JSON: {e}")
            return [
                "What are the key drivers behind this?",
                "How does this compare to the previous period?",
                "Can we break this down by dimension?",
            ]
