"""Graph topology, conditional routing, and the HITL checkpoint.

Builds a ``StateGraph(AgentState)`` with five agents, a self-correction loop
gated on the evaluator's quality score, and a human-in-the-loop checkpoint
via ``interrupt_before=["drafter"]`` backed by ``MemorySaver``.

.. code-block:: text

    START -> researcher -> analyzer -> evaluator --+-> researcher   (loop)
                                                    +-> human_approval
                                                          |
                                                          v (interrupt)
                                                      drafter -> END
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from config import MAX_RESEARCH_ITERATIONS, QUALITY_THRESHOLD
from nodes import (
    AnalyzerNode,
    DrafterNode,
    EvaluatorNode,
    HumanApprovalNode,
    ResearcherNode,
)
from state import AgentState


# --------------------------------------------------------------------------- #
# Conditional routing functions
# --------------------------------------------------------------------------- #
def route_after_evaluation(state: AgentState) -> str:
    """Self-correction routing after the evaluator.

    Returns:
        ``"researcher"`` when the quality score is below threshold and the
        retry budget (``iteration_count < MAX_RESEARCH_ITERATIONS``) is not
        exhausted — routing the graph back to research with the evaluator's
        ``feedback`` to close the identified gaps. Otherwise ``"human_approval"``.
    """

    score = state.get("quality_score", 0.0)
    iterations = state.get("iteration_count", 0)
    needs_more_research = score < QUALITY_THRESHOLD and iterations < MAX_RESEARCH_ITERATIONS
    return "researcher" if needs_more_research else "human_approval"


def route_after_approval(state: AgentState) -> str:
    """Post-approval routing from the human-in-the-loop gate.

    Always points at ``"drafter"``; the real pause is the
    ``interrupt_before=["drafter"]`` checkpoint. A rejection is expressed by
    the operator *not* resuming the thread (or resuming with
    ``human_approved`` left ``False``), which :class:`DrafterNode` enforces by
    emitting an explicit rejection artifact instead of a report. Routing is
    decided before the interrupt fires, so a state-based END branch here would
    be evaluated too early to reflect the operator decision.
    """

    return "drafter"


# --------------------------------------------------------------------------- #
# Graph construction
# --------------------------------------------------------------------------- #
def build_graph(
    llm: Optional[Any] = None,
    search_tool: Optional[Callable[[str], list]] = None,
    checkpointer: Optional[Any] = None,
):
    """Assemble and compile the market intelligence graph.

    Args:
        llm: chat model for the analyzer/drafter (``None`` = deterministic
            offline fallbacks).
        search_tool: callable ``(query) -> list[dict]`` (``None`` = best
            available: Tavily -> Serper -> mock).
        checkpointer: checkpoint backend (``None`` = in-memory
            :class:`MemorySaver`). Pass a ``SqliteSaver`` / ``PostgresSaver``
            for cross-process persistence.

    Returns:
        A compiled ``CompiledStateGraph`` checkpointed and interrupted before
        ``drafter`` for human approval.
    """

    builder = StateGraph(AgentState)

    builder.add_node("researcher", ResearcherNode(search_tool))
    builder.add_node("analyzer", AnalyzerNode(llm))
    builder.add_node("evaluator", EvaluatorNode())
    builder.add_node("human_approval", HumanApprovalNode())
    builder.add_node("drafter", DrafterNode(llm))

    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "analyzer")
    builder.add_edge("analyzer", "evaluator")

    builder.add_conditional_edges(
        "evaluator",
        route_after_evaluation,
        {"researcher": "researcher", "human_approval": "human_approval"},
    )

    # HITL gate: routing to drafter is unconditional — the actual pause is the
    # interrupt_before checkpoint compiled below.
    builder.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"drafter": "drafter"},
    )

    builder.add_edge("drafter", END)

    return builder.compile(
        checkpointer=checkpointer or MemorySaver(),  # HITL checkpointing
        interrupt_before=["drafter"],                # HITL pause before report drafting
    )


# Convenience singleton mirroring the default configuration.
graph = build_graph()
