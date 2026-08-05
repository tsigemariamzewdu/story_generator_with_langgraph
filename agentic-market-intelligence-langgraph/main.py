"""CLI entry point for the market intelligence pipeline.

Drives the LangGraph workflow end-to-end: starts the autonomous research
loop, surfaces the evaluator score and feedback, pauses at the
human-in-the-loop checkpoint, and resumes on operator approval to emit the
final structured JSON report.

Usage examples
--------------
Run the full flow (interactive HITL approval)::

    python main.py run "Salesforce"

Run fully automated (auto-approve)::

    python main.py run "Salesforce" --auto-approve

Run offline with mocked search + template drafting (no API keys)::

    python main.py run "Salesforce" --offline --auto-approve

Resume an interrupted thread with an explicit decision::

    python main.py resume --thread-id mi-abc123 --approve

Inspect a thread's checkpointed state::

    python main.py inspect --thread-id mi-abc123
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional

from config import get_llm, has_llm_config, has_search_config
from graph import build_graph
from state import AgentState, CompetitorMetrics

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
CHECKPOINT_DB = Path(__file__).resolve().parent / "checkpoints.db"


def _build_checkpointer():
    """SQLite-backed checkpointer so threads survive across CLI processes.

    The programmatic default in ``graph.py`` stays :class:`MemorySaver` (per
    the HITL spec); the CLI trades that for on-disk persistence so that
    ``resume`` / ``inspect`` work across separate invocations.
    """

    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(
        sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    )


def _graph_for(llm: Optional[object] = None):
    """Build the compiled graph using the CLI's persistent checkpointer."""

    return build_graph(llm=llm, checkpointer=_build_checkpointer())


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _print_updates(stream) -> None:
    """Pretty-print each node update emitted by ``graph.stream``."""

    for update in stream:
        for node, payload in update.items():
            if node == "__end__":
                continue
            keys = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            print(f"  [node] {node}  ->  {keys}")


def _preview(state: Dict) -> None:
    """Render a human-readable summary of the checkpointed state."""

    print("\n" + "=" * 64)
    print("  HUMAN-IN-THE-LOOP REVIEW")
    print("=" * 64)
    metrics: Optional[CompetitorMetrics] = state.get("structured_insights")
    print(f"  Target company : {state.get('target_company')}")
    print(f"  Quality score  : {state.get('quality_score', 0.0):.3f}")
    print(f"  Retry loops    : {state.get('iteration_count', 0)}")
    print(f"  Source records : {len(state.get('raw_search_data', []))}")
    if not has_search_config():
        print("  Warning        : using mock search fallback; configure TAVILY_API_KEY or SERPER_API_KEY for live web results.")
    if metrics:
        print(f"  Pricing        : {metrics.pricing_model or 'MISSING'}")
        print(f"  Target audience: {metrics.target_audience or 'MISSING'}")
        vps = ", ".join(metrics.key_value_propositions[:2]) or "MISSING"
        print(f"  Value props    : {vps}")
        print(f"  Source URLs    : {len(metrics.source_urls)}")
    feedback = state.get("feedback")
    if feedback:
        print("  Feedback:")
        for line in feedback.splitlines():
            print(f"    {line}")
    print("=" * 64)


def _save_report(thread_id: str, final_report: Optional[str]) -> Optional[Path]:
    if not final_report:
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{thread_id}.json"
    path.write_text(final_report, encoding="utf-8")
    return path


def _emit_final(final_report: Optional[str], as_json: bool) -> None:
    if not final_report:
        print("No final report produced.")
        return
    if as_json:
        print(json.dumps(json.loads(final_report), indent=2, ensure_ascii=False))
    else:
        report = json.loads(final_report)
        summary = report.get("research_report", {}).get("metrics", {}).get("company_overview", "")
        print("\n[DONE] Research report drafted.")
        print(f"  Overview : {summary[:120]}")
        print(f"  Pricing  : {report.get('research_report', {}).get('metrics', {}).get('pricing_model')}")


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    """Start a new pipeline run and handle the HITL checkpoint."""

    thread_id = args.thread_id or f"mi-{uuid.uuid4().hex[:8]}"
    llm = None if args.offline or not has_llm_config() else get_llm(args.llm_model)
    graph = _graph_for(llm=llm)
    cfg = _thread_config(thread_id)

    mode = "offline (mock search + template drafting)" if llm is None else f"live (LLM={args.llm_model or 'default'})"
    print(f"[run] thread={thread_id} mode={mode}")
    print(f"[run] researching: {args.company}")
    if not has_search_config() and not args.offline:
        print("[run] warning: no live search provider configured; results will come from mock fallback data.")

    initial: AgentState = {
        "target_company": args.company,
        "raw_search_data": [],
        "structured_insights": None,
        "quality_score": 0.0,
        "feedback": "",
        "human_approved": False,
        "final_report": None,
        "iteration_count": 0,
    }

    _print_updates(graph.stream(initial, cfg, stream_mode="updates"))

    snapshot = graph.get_state(cfg)
    if snapshot.next:
        print(f"[run] interrupted before node(s): {list(snapshot.next)}")
        _preview(snapshot.values)

        if args.auto_approve:
            decision = "y"
        else:
            try:
                decision = input("Approve research and draft the report? [y/N]: ").strip().lower()
            except EOFError:
                decision = "n"

        if decision in ("y", "yes"):
            graph.update_state(cfg, {"human_approved": True})
            print("[run] approved — resuming to drafter...")
            _print_updates(graph.stream(None, cfg, stream_mode="updates"))
        else:
            graph.update_state(cfg, {"human_approved": False})
            print("[run] rejected — no report drafted. Thread preserved.")
            print(f"[run] resume later with: python main.py resume --thread-id {thread_id} --approve")
            return 1
    else:
        print("[run] graph finished without an interrupt.")

    final_state = graph.get_state(cfg).values
    saved = _save_report(thread_id, final_state.get("final_report"))
    _emit_final(final_state.get("final_report"), args.json)
    if saved:
        print(f"[run] report saved to: {saved}")
    print(f"[run] thread-id (keep for resume/inspect): {thread_id}")
    return 0


def resume(args: argparse.Namespace) -> int:
    """Resume an interrupted thread with an explicit operator decision."""

    llm = None if args.offline or not has_llm_config() else get_llm()
    graph = _graph_for(llm=llm)
    cfg = _thread_config(args.thread_id)
    snapshot = graph.get_state(cfg)
    if not snapshot.next:
        print(f"[resume] thread '{args.thread_id}' is not interrupted (next={snapshot.next}).")
        return 1

    if args.approve:
        graph.update_state(cfg, {"human_approved": True})
        print("[resume] approved — resuming...")
        _print_updates(graph.stream(None, cfg, stream_mode="updates"))
        final_state = graph.get_state(cfg).values
        saved = _save_report(args.thread_id, final_state.get("final_report"))
        _emit_final(final_state.get("final_report"), args.json)
        if saved:
            print(f"[resume] report saved to: {saved}")
    else:
        graph.update_state(cfg, {"human_approved": False})
        print("[resume] rejected — thread preserved, no report drafted.")
    return 0


def inspect(args: argparse.Namespace) -> int:
    """Show the checkpointed state of a thread without mutating it."""

    graph = _graph_for()
    cfg = _thread_config(args.thread_id)
    snapshot = graph.get_state(cfg)
    print(f"[inspect] thread={args.thread_id}")
    print(f"[inspect] next node(s): {list(snapshot.next)}")
    if snapshot.next:
        _preview(snapshot.values)
    else:
        final = snapshot.values.get("final_report")
        if final:
            print("[inspect] thread completed. Final report preview:")
            _emit_final(final, as_json=True)
        else:
            print("[inspect] thread has no report yet.")
    return 0


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-market-intelligence",
        description="Autonomous market intelligence & competitor analysis pipeline (LangGraph).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the full pipeline for a company.")
    p_run.add_argument("company", help="Competitor name or industry keyword.")
    p_run.add_argument("--thread-id", default=None, help="Reusable thread id (default: auto).")
    p_run.add_argument("--llm-model", default=None, help="Override <provider>:<model>, e.g. openai:gpt-4o.")
    p_run.add_argument("--auto-approve", action="store_true", help="Skip the HITL prompt and approve.")
    p_run.add_argument("--offline", action="store_true", help="Force mock search + template drafting.")
    p_run.add_argument("--json", action="store_true", help="Print the final report as raw JSON.")
    p_run.set_defaults(func=run)

    p_resume = sub.add_parser("resume", help="Resume an interrupted thread.")
    p_resume.add_argument("--thread-id", required=True, help="Thread id from `run`.")
    p_resume.add_argument("--approve", action="store_true", help="Approve and resume drafting.")
    p_resume.add_argument("--reject", action="store_true", help="Reject; keep thread preserved.")
    p_resume.add_argument("--offline", action="store_true", help="Force template drafting on resume.")
    p_resume.add_argument("--json", action="store_true", help="Print the final report as raw JSON.")
    p_resume.set_defaults(func=resume)

    p_inspect = sub.add_parser("inspect", help="Inspect a thread's checkpointed state.")
    p_inspect.add_argument("--thread-id", required=True, help="Thread id from `run`.")
    p_inspect.set_defaults(func=inspect)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
