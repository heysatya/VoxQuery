import base64
import csv
import io
import os
from dataclasses import asdict

import httpx
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from lib.pipeline.auth import verify_auth
from lib.pipeline.rate_limiter import check_rate_limit
from lib.pipeline.guardrails import run_query_pipeline, PipelineSuccess
from lib.langgraph.pipeline_graph import run_pipeline_graph
from lib.query_sources.resolver import QuerySourceResolver
from lib.llm.sql_generator import generate_sql
from lib.tts.summary import generate_tts_summary
from lib.chart.render import build_chart_html

app = FastAPI(title="Voxquery")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
resolver = QuerySourceResolver()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
COOKIE_NAME = "sb_access_token"

# Demo-only in-memory store of each user's last result, so /csv and /sql can
# serve it without re-running the query. Swap for a real session store
# (Redis, a DB table) before production use — this does not survive
# multiple server instances any more than the rate limiter does.
_last_result_store: dict[str, dict] = {}


# --------------------------------------------------------------------------
# No-JS web UI
# --------------------------------------------------------------------------

def _get_session_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    auth_result = verify_auth(f"Bearer {token}")
    return auth_result if auth_result.ok else None


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_submit(email: str = Form(...), password: str = Form(...)):
    """
    Plain server-side password grant against Supabase's auth REST endpoint —
    no browser JS/SDK required. Fine for an internal exec tool; if you later
    need SSO/OAuth providers, that flow does typically require a small
    amount of browser-side redirect handling.
    """
    response = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=10.0,
    )
    if response.status_code != 200:
        return HTMLResponse(
            templates.get_template("login.html").render(request={}, error="Invalid email or password."),
            status_code=401,
        )

    access_token = response.json()["access_token"]
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(key=COOKIE_NAME, value=access_token, httponly=True, secure=True, samesite="lax")
    return redirect


@app.get("/logout")
def logout():
    redirect = RedirectResponse(url="/login", status_code=303)
    redirect.delete_cookie(COOKIE_NAME)
    return redirect


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "predetermined_queries": resolver.load_predetermined_queries(),
            "question": None,
            "chart_html": None,
            "rationale": None,
            "dedup_warning": None,
            "summary_text": None,
            "audio_data_uri": None,
            "error": None,
        },
    )


def _render_result(request: Request, user_id: str, question: str, pipeline_result):
    if not pipeline_result.ok:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "predetermined_queries": resolver.load_predetermined_queries(),
                "question": question,
                "chart_html": None,
                "rationale": None,
                "dedup_warning": None,
                "summary_text": None,
                "audio_data_uri": None,
                "error": pipeline_result.error,
            },
        )

    result: PipelineSuccess = pipeline_result
    _last_result_store[user_id] = {"sql": result.sql, "columns": result.result.columns, "rows": result.result.rows}

    chart_html = build_chart_html(result.chart, result.result)
    tts = generate_tts_summary(question, result.result)
    audio_data_uri = f"data:audio/mpeg;base64,{tts.audio_base64}" if tts.audio_base64 else None

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "predetermined_queries": resolver.load_predetermined_queries(),
            "question": question,
            "chart_html": chart_html,
            "rationale": result.chart.rationale,
            "dedup_warning": result.dedup_warning,
            "summary_text": tts.summary_text,
            "audio_data_uri": audio_data_uri,
            "error": None,
        },
    )


@app.post("/ask", response_class=HTMLResponse)
def ask(request: Request, question: str = Form(...), engine: str = Query("guardrails")):
    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    rate_limit = check_rate_limit(user.user_id)
    if not rate_limit.ok:
        return HTMLResponse("Rate limit exceeded. Please wait a moment before trying again.", status_code=429)

    generated = generate_sql(question, schema_context="", conversation_history="")
    candidate = resolver.from_llm(generated.sql, generated.confidence)

    if engine == "langgraph":
        state = run_pipeline_graph(candidate, schema_context="")
        # Normalize the graph's dict state into the same shape as the guardrails pipeline result.
        if state.get("failure_stage") or state.get("validation_error"):
            from lib.pipeline.guardrails import PipelineFailure
            pipeline_result = PipelineFailure(
                ok=False,
                stage=state.get("failure_stage") or "validation",
                error=state.get("failure_message") or state.get("validation_error"),
            )
        else:
            pipeline_result = PipelineSuccess(
                ok=True,
                sql=state["current_sql"],
                source=candidate.source,
                result=state["result"],
                chart=state["chart"],
                dedup_warning=state.get("dedup_warning"),
            )
    else:
        pipeline_result = run_query_pipeline(candidate, schema_context_for_retry="")

    return _render_result(request, user.user_id, question, pipeline_result)


@app.get("/ask-predetermined", response_class=HTMLResponse)
def ask_predetermined(request: Request, predetermined_id: str = Query(...)):
    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    candidate = resolver.from_predetermined_id(predetermined_id)
    if not candidate:
        return HTMLResponse(f"Unknown predetermined query id: {predetermined_id}", status_code=400)

    pipeline_result = run_query_pipeline(candidate, schema_context_for_retry="")
    return _render_result(request, user.user_id, candidate.label or predetermined_id, pipeline_result)


@app.get("/csv")
def download_csv(request: Request):
    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    stored = _last_result_store.get(user.user_id)
    if not stored:
        return HTMLResponse("No result to export yet — ask a question first.", status_code=404)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[c.name for c in stored["columns"]])
    writer.writeheader()
    writer.writerows(stored["rows"])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=voxquery-result.csv"},
    )


@app.get("/sql", response_class=HTMLResponse)
def show_sql(request: Request):
    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    stored = _last_result_store.get(user.user_id)
    sql = stored["sql"] if stored else "No query run yet."
    return templates.TemplateResponse("sql.html", {"request": request, "sql": sql})


# --------------------------------------------------------------------------
# JSON API routes — for external systems, mobile clients, or a future
# JS frontend, if you ever want one alongside this no-JS UI.
# --------------------------------------------------------------------------

@app.post("/api/query")
async def api_query(request: Request):
    auth_result = verify_auth(request.headers.get("authorization"))
    if not auth_result.ok:
        return JSONResponse({"error": auth_result.error}, status_code=401)

    rate_limit = check_rate_limit(auth_result.user_id)
    if not rate_limit.ok:
        return JSONResponse({"error": "Rate limit exceeded."}, status_code=429)

    body = await request.json()
    candidate = _resolve_candidate_from_body(body)
    if isinstance(candidate, JSONResponse):
        return candidate

    pipeline_result = run_query_pipeline(candidate, schema_context_for_retry=body.get("schemaContext", ""))
    return _pipeline_result_to_json(pipeline_result, candidate)


@app.post("/api/query-langgraph")
async def api_query_langgraph(request: Request):
    auth_result = verify_auth(request.headers.get("authorization"))
    if not auth_result.ok:
        return JSONResponse({"error": auth_result.error}, status_code=401)

    rate_limit = check_rate_limit(auth_result.user_id)
    if not rate_limit.ok:
        return JSONResponse({"error": "Rate limit exceeded."}, status_code=429)

    body = await request.json()
    candidate = _resolve_candidate_from_body(body)
    if isinstance(candidate, JSONResponse):
        return candidate

    state = run_pipeline_graph(candidate, schema_context=body.get("schemaContext", ""))
    if state.get("failure_stage") or state.get("validation_error"):
        return JSONResponse(
            {"error": state.get("failure_message") or state.get("validation_error"), "stage": state.get("failure_stage") or "validation"},
            status_code=422,
        )
    return JSONResponse({
        "sql": state["current_sql"],
        "source": candidate.source,
        "columns": [asdict(c) for c in state["result"].columns],
        "rows": state["result"].rows,
        "rowCount": state["result"].row_count,
        "chart": asdict(state["chart"]),
        "dedupWarning": state.get("dedup_warning"),
    })


@app.post("/api/tts")
async def api_tts(request: Request):
    auth_result = verify_auth(request.headers.get("authorization"))
    if not auth_result.ok:
        return JSONResponse({"error": auth_result.error}, status_code=401)

    rate_limit = check_rate_limit(auth_result.user_id)
    if not rate_limit.ok:
        return JSONResponse({"error": "Rate limit exceeded."}, status_code=429)

    body = await request.json()
    from lib.db.types import QueryExecutionResult, ColumnInfo
    result = QueryExecutionResult(
        columns=[ColumnInfo(**c) for c in body.get("columns", [])],
        rows=body.get("rows", []),
        row_count=body.get("rowCount", 0),
        truncated=False,
        execution_ms=body.get("executionMs", 0),
    )
    tts = generate_tts_summary(body.get("question", ""), result)
    return JSONResponse({"summaryText": tts.summary_text, "audioBase64": tts.audio_base64})


def _resolve_candidate_from_body(body: dict):
    if body.get("predeterminedId"):
        candidate = resolver.from_predetermined_id(body["predeterminedId"])
        if not candidate:
            return JSONResponse({"error": f'Unknown predetermined query id: {body["predeterminedId"]}'}, status_code=400)
        return candidate
    if body.get("ragRetrievedSql"):
        return resolver.from_rag_retrieval(body["ragRetrievedSql"], body.get("ragChunkLabel", "rag-match"))
    if body.get("externalSql"):
        return resolver.from_external_system(body["externalSql"], body.get("externalSystemLabel", "external"))
    if body.get("generatedSql"):
        return resolver.from_llm(body["generatedSql"], body.get("confidence", 0.5))
    return JSONResponse(
        {"error": "Request must include one of: generatedSql, ragRetrievedSql, predeterminedId, externalSql."},
        status_code=400,
    )


def _pipeline_result_to_json(pipeline_result, candidate):
    if not pipeline_result.ok:
        return JSONResponse({"error": pipeline_result.error, "stage": pipeline_result.stage}, status_code=422)
    return JSONResponse({
        "sql": pipeline_result.sql,
        "source": pipeline_result.source,
        "columns": [asdict(c) for c in pipeline_result.result.columns],
        "rows": pipeline_result.result.rows,
        "rowCount": pipeline_result.result.row_count,
        "chart": asdict(pipeline_result.chart),
        "dedupWarning": pipeline_result.dedup_warning,
    })
