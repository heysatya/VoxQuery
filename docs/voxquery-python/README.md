# Voxquery (Python) — 4.5, 4.6, 4.7

Same architecture as the TypeScript version, rebuilt entirely in Python:
FastAPI instead of Next.js API routes, sqlglot instead of node-sql-parser
(this is actually the tool the original spec named), Plotly + Jinja2
templates instead of React + Recharts, and LangGraph's native Python
package instead of its JS port.

**No custom JavaScript anywhere in this project.** Plotly generates its own
`<script>` tag internally when you call `fig.to_html()` — that's a library
shipping its own code, not something you write or maintain. Everything you
read, edit, and reason about is Python and plain HTML/Jinja2 templates.

## Running locally

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
export $(cat .env | xargs)  # or use python-dotenv / your shell's env loading
uvicorn app.main:app --reload
# visit http://localhost:8000/login
```

## Switching backend databases

Edit **one file**: `config/db_config.json` → `active_provider`. Same
pattern as the TypeScript version — `lib/db/factory.py` is the only place
that reads this key, and everything downstream only talks to the
`DBAdapter` interface in `lib/db/types.py`.

## Accepting queries from multiple sources

`lib/query_sources/resolver.py` normalizes four input types
(`llm_generated`, `rag_retrieved`, `predetermined_file`, `external_system`)
into one `QueryCandidate` before anything is validated — identical design
to the TypeScript version, just Python syntax.

## Two orchestration styles, same checkpoints

- `lib/pipeline/guardrails.py` — plain function chain.
- `lib/langgraph/pipeline_graph.py` — the same sequence as a LangGraph
  `StateGraph`, using the real Python `langgraph` package (not a port).

The `/ask` web route and the `/api/query` / `/api/query-langgraph` JSON
routes both exist so you can pick per request (`?engine=langgraph` on `/ask`,
or call the different JSON endpoint directly).

## No-JS web UI

- `GET /login`, `POST /login` — signs in against Supabase's password-grant
  REST endpoint directly (no browser SDK), sets an HTTP-only cookie.
- `GET /` — the ask form.
- `POST /ask` — runs the pipeline, renders a Plotly chart or HTML table,
  plays the TTS summary via a native `<audio>` tag with a base64 data URI.
- `GET /csv` — downloads the last result as CSV.
- `GET /sql` — shows the last executed SQL.

If you later need SSO/OAuth sign-in instead of email+password, that
typically does require a small amount of browser-side redirect handling —
worth knowing up front, since it's the one place a fully server-rendered
Python app usually can't avoid the browser entirely.

## What still needs your input

- Wiring 4.4's actual RAG retrieval so `ragRetrievedSql` / schema context
  come from your real pgvector setup instead of empty placeholders.
- Creating the actual read-only Postgres role in Supabase (see
  ARCHITECTURE.md, Section 6).
- Replacing the in-memory rate limiter and last-result store with Redis or
  a database table before real production traffic — neither survives
  multiple server instances.
- Wiring Langfuse logging into the pipeline checkpoints.
