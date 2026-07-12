from __future__ import annotations

from openai import OpenAI

SYSTEM_PROMPT = """\
You are a DuckDB SQL expert. Given the schema context below, write a single valid DuckDB SQL \
query that answers the user's question. Return ONLY the SQL, no explanation.

Schema context:
{context}
"""


class SQLGenerator:
    def __init__(self, model: str = "gpt-4o", api_key: str = "") -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key)

    def generate(self, question: str, context: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
                {"role": "user", "content": question},
            ],
            max_tokens=512,
            temperature=0,
        )
        return response.choices[0].message.content.strip()
