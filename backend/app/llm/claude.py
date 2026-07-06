import logging

import sqlglot
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.llm.adapter import LlmAdapter, SqlGenerationResult
from langfuse import observe, get_client

logger = logging.getLogger(__name__)

class ClaudeAdapter(LlmAdapter):
    def __init__(self, client: AsyncAnthropic) -> None:
        self.client = client
        self.model_name = get_settings().canonical_sql_model

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def generate_sql(self, submitted_text: str, *, resolved_metric: str | None = None) -> SqlGenerationResult:
        get_client().update_current_generation(
            name="claude-sql-generation",
            input={"submitted_text": submitted_text, "resolved_metric": resolved_metric},
            model=self.model_name
        )
        prompt = f"""
        You are an expert Snowflake SQL generator. Generate a read-only SQL query for the following request.
        Do NOT wrap the SQL in markdown blocks. Return ONLY valid SQL. 
        Always LIMIT to 10000 rows maximum.
        
        Request: {submitted_text}
        """
        if resolved_metric:
            prompt += f"\nNote: The user clarified they want the '{resolved_metric}' metric."

        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        sql = response.content[0].text.strip()
        
        # Strip markdown if LLM disobeyed
        if sql.startswith("```sql"):
            sql = sql[6:]
        if sql.endswith("```"):
            sql = sql[:-3]
        sql = sql.strip()

        # Validate with sqlglot
        validation_passed = True
        try:
            # Parse as snowflake dialect
            parsed = sqlglot.parse_one(sql, read="snowflake")
            
            # Simple check for read-only
            if not isinstance(parsed, sqlglot.exp.Select):
                validation_passed = False
                
        except Exception as e:
            logger.warning(f"SQL validation failed: {e}")
            validation_passed = False

        # In a real app we might ask Claude for confidence score, here we fake 0.95 if it passed validation
        confidence = 0.95 if validation_passed else 0.4
        
        result = SqlGenerationResult(sql=sql, llm_self_confidence=confidence, validation_passed=validation_passed)
        get_client().update_current_generation(output={"sql": result.sql, "confidence": result.llm_self_confidence, "validation_passed": validation_passed})
        return result

    @observe(as_type="generation", capture_input=False, capture_output=False)
    async def generate_clarification(self, dominant_signal: str) -> tuple[str, list[str]]:
        get_client().update_current_generation(
            name="claude-clarification-generation",
            input={"dominant_signal": dominant_signal},
            model=self.model_name
        )
        prompt = f"""
        You are an expert Data Analyst AI. The user's query is ambiguous regarding the metric '{dominant_signal}'.
        Generate a clarification question to ask the user, and provide 2 to 4 options for them to choose from.
        Respond ONLY with a valid JSON object matching this schema:
        {{
            "question": "The question to ask the user",
            "options": ["Option 1", "Option 2", ...]
        }}
        """

        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.content[0].text.strip()
        
        import json
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
            get_client().update_current_generation(output={"question": question, "options": options})
            return question, options
        except Exception as e:
            logger.error(f"Failed to parse clarification JSON: {e}")
            question = f"Could you clarify regarding {dominant_signal}?"
            options = ["Option A", "Option B", "Skip"]
            get_client().update_current_generation(output={"question": question, "options": options, "error": str(e)})
            return question, options
