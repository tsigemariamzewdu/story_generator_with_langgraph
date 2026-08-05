"""FastAPI backend for the market intelligence pipeline.

Endpoints
---------
POST   /runs                        Start a new pipeline run (non-blocking).
GET    /runs/{thread_id}            Poll run status + HITL review data.
POST   /runs/{thread_id}/approve    Approve HITL checkpoint and resume drafter.
POST   /runs/{thread_id}/reject     Reject HITL checkpoint; no report drafted.
GET    /runs/{thread_id}/report     Fetch the final structured JSON report.
GET    /health                      Liveness check.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_llm, has_llm_config, has_search_config
from graph import build_graph
from state import AgentState, CompetitorMetrics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
CHECKPOINT_DB = Path(__file__).resolve().parent / "checkpoints.db"
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Market Intelligence API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — lock to frontend origin in production via ALLOWED_ORIGINS env var
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@contextmanager
def _get_db():
    """Context manager that opens and always closes the SQLite connection."""
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def _checkpointer():
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return SqliteSaver(conn), conn


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# --------------------------------------------------------------------------- #
# In-memory run registry  {thread_id -> status}
# --------------------------------------------------------------------------- #
_runs: Dict[str, str] = {}   # "running" | "awaiting_approval" | "completed" | "rejected" | "error"
_errors: Dict[str, str] = {}


# --------------------------------------------------------------------------- #
# Request / Response schemas
# --------------------------------------------------------------------------- #
_COMPANY_RE = re.compile(r"^[\w\s\-\.&,'()]+$")


class StartRunRequest(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    offline: bool = False

    @field_validator("company")
    @classmethod
    def sanitize_company(cls, v: str) -> str:
        v = v.strip()
        if not _COMPANY_RE.match(v):
            raise ValueError("Company name contains invalid characters.")
        return v


class ApproveRequest(BaseModel):
    pass


class RunStatusResponse(BaseModel):
    thread_id: str
    status: str
    company: Optional[str] = None
    quality_score: Optional[float] = None
    iteration_count: Optional[int] = None
    source_records: Optional[int] = None
    next_nodes: List[str] = []
    metrics_preview: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None


# --------------------------------------------------------------------------- #
# Background pipeline runner
# --------------------------------------------------------------------------- #
def _run_pipeline(thread_id: str, company: str, offline: bool) -> None:
    """Runs the graph synchronously in a background thread until HITL interrupt."""
    conn = None
    try:
        llm = None if offline or not has_llm_config() else get_llm()
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        graph = build_graph(llm=llm, checkpointer=SqliteSaver(conn))
        cfg = _thread_config(thread_id)

        initial: AgentState = {
            "target_company": company,
            "raw_search_data": [],
            "structured_insights": None,
            "quality_score": 0.0,
            "feedback": "",
            "human_approved": False,
            "final_report": None,
            "iteration_count": 0,
        }

        for _ in graph.stream(initial, cfg, stream_mode="updates"):
            pass

        snapshot = graph.get_state(cfg)
        if snapshot.next:
            _runs[thread_id] = "awaiting_approval"
        else:
            _runs[thread_id] = "completed"
            _save_report(thread_id, snapshot.values.get("final_report"))

    except Exception as exc:
        logger.exception("Pipeline error for thread %s", thread_id)
        _runs[thread_id] = "error"
        _errors[thread_id] = str(exc)
    finally:
        if conn:
            conn.close()


def _resume_pipeline(thread_id: str) -> None:
    """Resumes the graph after HITL approval until completion."""
    conn = None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        graph = build_graph(
            llm=get_llm() if has_llm_config() else None,
            checkpointer=SqliteSaver(conn),
        )
        cfg = _thread_config(thread_id)
        graph.update_state(cfg, {"human_approved": True})

        for _ in graph.stream(None, cfg, stream_mode="updates"):
            pass

        snapshot = graph.get_state(cfg)
        _runs[thread_id] = "completed"
        _save_report(thread_id, snapshot.values.get("final_report"))

    except Exception as exc:
        logger.exception("Resume error for thread %s", thread_id)
        _runs[thread_id] = "error"
        _errors[thread_id] = str(exc)
    finally:
        if conn:
            conn.close()


def _save_report(thread_id: str, final_report: Optional[str]) -> None:
    if final_report:
        (OUTPUT_DIR / f"{thread_id}.json").write_text(final_report, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.post("/runs", status_code=202)
@limiter.limit("10/minute")
async def start_run(request: Request, body: StartRunRequest, background_tasks: BackgroundTasks):
    """Start a new pipeline run. Returns immediately with a thread_id to poll."""
    thread_id = f"mi-{uuid.uuid4().hex[:8]}"
    _runs[thread_id] = "running"
    background_tasks.add_task(_run_pipeline, thread_id, body.company, body.offline)
    return {"thread_id": thread_id, "status": "running"}


@app.get("/runs/{thread_id}", response_model=RunStatusResponse)
@limiter.limit("60/minute")
async def get_run_status(request: Request, thread_id: str):
    """Poll the current status of a run. Returns HITL review data when awaiting approval."""
    if thread_id not in _runs:
        raise HTTPException(status_code=404, detail="Thread not found")

    status = _runs[thread_id]
    response = RunStatusResponse(thread_id=thread_id, status=status)

    if status == "error":
        response.error = _errors.get(thread_id)
        return response

    conn = None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        graph = build_graph(checkpointer=SqliteSaver(conn))
        cfg = _thread_config(thread_id)
        snapshot = graph.get_state(cfg)
        values = snapshot.values

        response.company = values.get("target_company")
        response.quality_score = values.get("quality_score")
        response.iteration_count = values.get("iteration_count", 0)
        response.source_records = len(values.get("raw_search_data", []))
        response.next_nodes = list(snapshot.next) if snapshot.next else []
        response.feedback = values.get("feedback") or None
        if not has_search_config():
            response.warning = "Using mock search — set TAVILY_API_KEY or SERPER_API_KEY for live data."

        metrics: Optional[CompetitorMetrics] = values.get("structured_insights")
        if metrics:
            response.metrics_preview = {
                "company_overview": metrics.company_overview,
                "pricing_model": metrics.pricing_model,
                "target_audience": metrics.target_audience,
                "key_value_propositions": metrics.key_value_propositions[:3],
                "strengths": metrics.strengths[:3],
                "weaknesses": metrics.weaknesses[:3],
                "competitors_mentioned": metrics.competitors_mentioned[:3],
                "market_positioning": metrics.market_positioning,
                "source_urls": metrics.source_urls[:5],
            }
    except Exception:
        logger.debug("State not yet written for thread %s", thread_id)
    finally:
        if conn:
            conn.close()

    return response


@app.post("/runs/{thread_id}/approve", status_code=202)
@limiter.limit("20/minute")
async def approve_run(request: Request, thread_id: str, background_tasks: BackgroundTasks):
    """Approve the HITL checkpoint and resume the drafter."""
    if thread_id not in _runs:
        raise HTTPException(status_code=404, detail="Thread not found")
    if _runs[thread_id] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"Run is not awaiting approval (status={_runs[thread_id]})")

    _runs[thread_id] = "running"
    background_tasks.add_task(_resume_pipeline, thread_id)
    return {"thread_id": thread_id, "status": "running", "message": "Approved — resuming drafter"}


@app.post("/runs/{thread_id}/reject", status_code=200)
@limiter.limit("20/minute")
async def reject_run(request: Request, thread_id: str):
    """Reject the HITL checkpoint. Thread is preserved but no report is drafted."""
    if thread_id not in _runs:
        raise HTTPException(status_code=404, detail="Thread not found")
    if _runs[thread_id] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"Run is not awaiting approval (status={_runs[thread_id]})")

    conn = None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        graph = build_graph(checkpointer=SqliteSaver(conn))
        graph.update_state(_thread_config(thread_id), {"human_approved": False})
    except Exception:
        logger.exception("Failed to update state on reject for thread %s", thread_id)
    finally:
        if conn:
            conn.close()

    _runs[thread_id] = "rejected"
    return {"thread_id": thread_id, "status": "rejected", "message": "Research rejected. No report drafted."}


@app.get("/runs/{thread_id}/report")
@limiter.limit("30/minute")
async def get_report(request: Request, thread_id: str):
    """Return the final structured JSON report for a completed run."""
    if thread_id not in _runs:
        raise HTTPException(status_code=404, detail="Thread not found")
    if _runs[thread_id] != "completed":
        raise HTTPException(status_code=409, detail=f"Report not ready (status={_runs[thread_id]})")

    report_path = OUTPUT_DIR / f"{thread_id}.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))

    # Fallback: read directly from graph state
    conn = None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
        graph = build_graph(checkpointer=SqliteSaver(conn))
        snapshot = graph.get_state(_thread_config(thread_id))
        raw = snapshot.values.get("final_report")
        if raw:
            return json.loads(raw)
    except Exception:
        logger.exception("Failed to read report from state for thread %s", thread_id)
    finally:
        if conn:
            conn.close()

    raise HTTPException(status_code=404, detail="Report file not found")


@app.get("/health")
async def health():
    return {"status": "healthy", "llm_configured": has_llm_config()}


# --------------------------------------------------------------------------- #
# Static frontend — mounted last so the API routes above take precedence.
# A single service then hosts both the API and the UI.
# --------------------------------------------------------------------------- #
_FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
