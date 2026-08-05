"""Multi-agent node implementations for the market intelligence pipeline.

Every node is a *callable class* injected with its dependencies (LLM, search
tool) so the graph stays easy to test and runs identically against live
providers or offline mocks. Each ``__call__`` receives the full
:class:`~state.AgentState` and returns only the state keys it owns.

Pipeline
--------
researcher -> analyzer -> evaluator -+-> researcher (self-correction loop)
                                    +-> human_approval -> [HITL interrupt]
                                                       -> drafter -> END
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from config import MAX_RESEARCH_ITERATIONS, QUALITY_THRESHOLD
from search import build_search_tool
from state import AgentState, CompetitorMetrics, OutreachDraft, ResearchReport


# --------------------------------------------------------------------------- #
# Shared text helpers
# --------------------------------------------------------------------------- #
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> List[str]:
    """Split free text into reasonably-sized sentences for heuristics."""

    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) >= 15]


_BOILERPLATE_MARKERS = (
    "cookie", "sign up", "signup", "subscribe", "newsletter", "javascript",
    "all rights reserved", "privacy policy", "terms of service",
    "terms of use", "get started", "learn more", "click here",
    "skip to content", "share on", "follow us", "open in new tab",
    "log in", "login", "register", "download now", "©",
)


def _is_boilerplate(sentence: str) -> bool:
    """Drop navigation/cookie/CTA noise that pollutes the heuristics."""

    lowered = sentence.lower()
    return any(marker in lowered for marker in _BOILERPLATE_MARKERS)


_PRICING_PATTERNS = [
    r"\$\s?\d",
    r"\bper (user|seat|month|year)\b",
    r"\bpricing\b",
    r"\bplans?\b",
    r"\btier\w*\b",
    r"\bcost(s|ing)?\b",
    r"\bprice\w*\b",
    r"\bfree trial\b",
    r"\bfreemium\b",
    r"\bbilling\b",
    r"\bsubscription\b",
    r"\bfees?\b",
    r"\bpaid\b",
    r"\bupgrade\b",
]

_AUDIENCE_PATTERNS = [
    r"\btarget audience\b",
    r"\bideal customer\b",
    r"\bICP\b",
    r"\bB2B\b",
    r"\bB2C\b",
    r"\bSMB\b",
    r"\bmid[- ]market\b",
    r"\benterprise\b",
    r"\bdemographics?\b",
    r"\baudience\b",
    r"\bbuyer persona\b",
    r"\btarget market\b",
    r"\baimed at\b",
    r"\bdesigned for\b",
    r"\bbuilt for\b",
    r"\bused by\b",
    r"\bserves?\b",
    r"\bcustomer base\b",
    r"\bfor (creatives|freelancers|solopreneurs|startups|small businesses|teams?|developers|designers|marketers|enterprises?)\b",
]

_VALUE_PATTERNS = [
    r"\bvalue proposition\b",
    r"\bbenefit\w*\b",
    r"\bdifferentiat\w*\b",
    r"\badvantage\w*\b",
    r"\bautomation\b",
    r"\bintegrat\w*\b",
    r"\bROI\b",
    r"\bscalab\w*\b",
    r"\bpayback\b",
    r"\bfeatures?\b",
    r"\buser[- ]friendly\b",
    r"\bease of use\b",
    r"\ball[- ]in[- ]one\b",
    r"\bbuilt[- ]in\b",
    r"\bcapabilit\w*\b",
    r"\bno[- ]code\b",
    r"\bworkflows?\b",
    r"\bcollaboration\b",
    r"\bperformance\b",
    r"\bcustomiz\w*\b",
]

_STRENGTH_PATTERNS = [
    r"\bstrength\w*",
    r"\bpros?\b",
    r"\bleader\b",
    r"\bleading\b",
    r"\bbest[- ]in[- ]class\b",
    r"\brecogni[sz]",
    r"\baward\w*",
    r"\btop\b",
    r"\bstrong\b",
    r"\bpopular\b",
    r"\bexcellent\b",
    r"\bpraised?\b",
    r"\bwell[- ]known\b",
    r"\brobust\b",
    r"\btrusted\b",
    r"\bdominant\b",
    r"\bNPS\b",
    r"\bmarket leader\b",
    r"\buser[- ]friendly\b",
    r"\beasy to use\b",
    r"\bintuitive\b",
    r"\bimpressive\b",
    r"\bhigh[- ]quality\b",
]

_WEAKNESS_PATTERNS = [
    r"\bweak\w*",
    r"\bcons?\b",
    r"\bcriticis\w*",
    r"\bcriticized\b",
    r"\blimitation\w*",
    r"\bdrawback\w*",
    r"\bdownside\w*",
    r"\bchallenge\w*",
    r"\bstruggl\w*",
    r"\bdifficult\w*",
    r"\bexpensive\b",
    r"\bcostly\b",
    r"\boverpriced\b",
    r"\bovervalu\w*\b",
    r"\blacks?\b",
    r"\black of\b",
    r"\bmissing\b",
    r"\boutdated\b",
    r"\bhowever\b",
    r"\bgaps?\b",
    r"\bcomplaints?\b",
    r"\bnegative\w*",
    r"\bshortcomings?\b",
    r"\bnot as\b",
    r"\bfalls? short\b",
    r"\bfails?\b",
    r"\bissues?\b",
    r"\bproblems?\b",
]

_COMPETITOR_PATTERNS = [
    r"\bcompetitor\w*",
    r"\balternative\w*",
    r"\brival\w*",
    r"\bvs\.?\b",
    r"\bversus\b",
    r"\bcompared?\b",
    r"\bcomparison\b",
    r"\bcompare\w*",
    r"\bmarket share\b",
    r"\blandscape\b",
    r"\bsubstitutes?\b",
    r"\bcategory peers\b",
    r"\bother (platforms|tools|options|products|solutions|players)\b",
]

_POSITIONING_PATTERNS = [
    r"\bposition",
    r"\bmarket share\b",
    r"\bGartner\b",
    r"\bMagic Quadrant\b",
    r"\bleader in\b",
    r"\bfast follower\b",
    r"\bfirst mover\b",
    r"\bdominant\b",
    r"\bniche\b",
    r"\bsegment\w*",
    r"\bmarket leader\b",
    r"\bincumbent\w*",
    r"\bshare of\b",
    r"\bcategory leader\b",
    r"\bpositioning\b",
]


def _claim(
    sentences: List[str],
    patterns: List[str],
    limit: int,
    exclude: Optional[set] = None,
    prefer_unclaimed: Optional[set] = None,
) -> List[str]:
    """Return up to ``limit`` unique sentences matching any pattern.

    ``exclude`` drops sentences already claimed by a sibling dimension.
    ``prefer_unclaimed`` (used for the opinion dimensions) collects sentences
    already claimed by the core dimensions as a *fallback* pool, so a thin
    corpus still yields findings instead of empty lists.
    """

    matchers = [re.compile(p, re.IGNORECASE) for p in patterns]
    hits: List[str] = []
    fallback: List[str] = []
    for sentence in sentences:
        if sentence in hits or sentence in fallback:
            continue
        if not any(m.search(sentence) for m in matchers):
            continue
        if prefer_unclaimed is not None:
            if sentence in prefer_unclaimed:
                fallback.append(sentence)
            else:
                hits.append(sentence)
        elif exclude is not None and sentence in exclude:
            continue
        else:
            hits.append(sentence)
        if len(hits) >= limit:
            return hits
    return (hits + fallback)[:limit]


def _clauses(sentences: List[str]) -> List[str]:
    """Split sentences into comma/semicolon clauses for finer-grained matches."""

    parts: List[str] = []
    for sentence in sentences:
        for chunk in re.split(r"[;,()]|\s-\s", sentence):
            chunk = chunk.strip().strip(".").strip()
            if len(chunk) >= 8:
                parts.append(chunk)
    return parts


# --------------------------------------------------------------------------- #
# 1. Researcher
# --------------------------------------------------------------------------- #
class ResearcherNode:
    """Autonomously searches the live web for competitive intelligence.

    Issues a base set of neutral research queries (pricing, audience, value
    propositions, competitors, news) plus targeted follow-up queries derived
    from the evaluator's ``feedback``, so every self-correction loop chases
    the exact gaps the previous analysis surfaced.
    """

    BASE_QUERIES = [
        "{company} pricing model plans 2026",
        "{company} target audience customers buyers market",
        "{company} value proposition competitors differentiators",
        "{company} strengths weaknesses market position latest news 2026",
    ]

    # topic -> extra queries; topics are matched as substrings of evaluator
    # feedback so the retry loop is fully driven by the evaluator.
    FEEDBACK_QUERIES = {
        "pricing": [
            "{company} pricing model tiers discounts annual cost",
            "{company} price points promotions annual billing",
        ],
        "target audience": [
            "{company} who uses customers buyer demographics",
            "{company} ideal customer profile buyer personas",
        ],
        "value proposition": [
            "{company} benefits features differentiators",
            "{company} advantages compared with competitors",
        ],
        "strength": [
            "{company} strengths reviews ratings awards",
        ],
        "weakness": [
            "{company} weaknesses limitations criticism cons",
        ],
        "competitor": [
            "{company} competitors alternatives comparison market share",
        ],
        "positioning": [
            "{company} market position analyst report Gartner",
        ],
        "source": [
            "{company} latest news press release funding",
        ],
    }

    def __init__(self, search_tool: Optional[Callable[[str], List[dict]]] = None) -> None:
        """Args: search_tool: callable ``(query) -> list[dict]`` of results."""
        self.search_tool = search_tool or build_search_tool()

    def _targeted_queries(self, feedback: str) -> List[str]:
        queries: List[str] = []
        for topic, templates in self.FEEDBACK_QUERIES.items():
            if topic in feedback.lower():
                queries.extend(templates)
        return queries

    def __call__(self, state: AgentState) -> dict:
        company: str = state["target_company"]
        feedback: str = state.get("feedback", "")

        queries = [q.format(company=company) for q in self.BASE_QUERIES]
        queries += [q.format(company=company) for q in self._targeted_queries(feedback)]

        results: List[dict] = []
        for query in queries:
            try:
                for hit in self.search_tool(query):
                    hit = dict(hit)
                    hit.setdefault("query", query)
                    results.append(hit)
            except Exception as exc:  # never let one provider failure kill the run
                results.append(
                    {
                        "title": f"Search failed for: {query}",
                        "url": "",
                        "content": f"ERROR: {exc}",
                        "source": "error",
                        "query": query,
                        "is_mock": False,
                    }
                )

        # iteration_count = number of self-correction loops taken. Feedback is
        # only present on retry passes, so the count advances exactly once per
        # loop and the evaluator's `iteration_count < 3` guard caps retries.
        iteration_count = state.get("iteration_count", 0)
        if feedback:
            iteration_count += 1

        return {
            "raw_search_data": results,
            "iteration_count": iteration_count,
        }


# --------------------------------------------------------------------------- #
# 2. Analyzer
# --------------------------------------------------------------------------- #
class AnalyzerNode:
    """Synthesizes raw search results into a strict ``CompetitorMetrics``.

    Uses ``llm.with_structured_output(CompetitorMetrics)`` when an LLM is
    configured. Without an LLM (offline/mock mode) a deterministic rule-based
    extractor parses the corpus instead, so the pipeline is fully executable
    with zero API keys.
    """

    def __init__(self, llm: Optional[Any] = None) -> None:
        """Args: llm: chat model supporting ``with_structured_output``."""
        self.llm = llm

    def __call__(self, state: AgentState) -> dict:
        company: str = state["target_company"]
        raw_search_data = state.get("raw_search_data", [])
        corpus = self._build_corpus(raw_search_data)
        source_urls = self._collect_source_urls(raw_search_data)
        if self.llm is not None:
            metrics = self._llm_extract(corpus, company, source_urls)
        else:
            metrics = self._heuristic_extract(corpus, company, source_urls)
        return {"structured_insights": metrics}

    @staticmethod
    def _collect_source_urls(raw_search_data: List[dict]) -> List[str]:
        urls: List[str] = []
        for item in raw_search_data:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if url and not url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")) and url not in urls:
                urls.append(url)
        return urls[:10]

    @staticmethod
    def _build_corpus(raw_search_data: List[dict]) -> List[str]:
        blocks: List[str] = []
        for item in raw_search_data:
            if not isinstance(item, dict):
                continue
            # Extract heuristics read the *content* of each result; titles and
            # URLs stay out so they don't pollute sentence matching. URLs are
            # surfaced separately via ``_collect_source_urls``.
            text = str(item.get("content", "")).strip()
            if not text and (item.get("title") or item.get("url")):
                text = " ".join(str(p) for p in (item.get("title"), item.get("url")) if p)
            if text:
                blocks.append(text)
        return blocks

    def _llm_extract(self, corpus: List[str], company: str, source_urls: List[str]) -> CompetitorMetrics:
        system = SystemMessage(
            content=(
                "You are a senior competitive-intelligence analyst. Extract "
                "structured findings from the research corpus into the exact "
                "schema provided. Use empty strings or empty lists for "
                "information that is NOT present in the corpus. Never "
                "invent facts. Only claims supported by the corpus may be "
                "recorded. Populate source_urls ONLY from the provided "
                "SOURCE URLS list that you actually used."
            )
        )
        human = HumanMessage(
            content=f"TARGET COMPANY:\n{company}\n\nRESEARCH CORPUS:\n\n"
            + "\n\n---\n\n".join(corpus)
            + f"\n\nSOURCE URLS:\n" + "\n".join(source_urls)
        )

        try:
            structured = self.llm.with_structured_output(
                CompetitorMetrics, method="function_calling"
            )
            raw = structured.invoke([system, human])
            if isinstance(raw, CompetitorMetrics):
                metrics = raw
            elif isinstance(raw, dict):
                metrics = CompetitorMetrics.model_validate(raw)
            else:
                metrics = CompetitorMetrics.model_validate_json(str(raw))
        except Exception:
            # If the provider output is malformed, degrade gracefully to the
            # deterministic extractor instead of failing the whole pipeline.
            return self._heuristic_extract(corpus, company, source_urls)

        # Backfill any dimension the LLM left empty with the heuristic
        # findings, so the report never shows gaps when evidence exists.
        return self._backfill(metrics, self._heuristic_extract(corpus, company, source_urls))

    @staticmethod
    def _backfill(
        metrics: CompetitorMetrics, heuristic: CompetitorMetrics
    ) -> CompetitorMetrics:
        if not metrics.company_overview:
            metrics.company_overview = heuristic.company_overview
        if not metrics.pricing_model:
            metrics.pricing_model = heuristic.pricing_model
        if not metrics.target_audience:
            metrics.target_audience = heuristic.target_audience
        if not metrics.key_value_propositions:
            metrics.key_value_propositions = heuristic.key_value_propositions
        if not metrics.competitors_mentioned:
            metrics.competitors_mentioned = heuristic.competitors_mentioned
        if not metrics.strengths:
            metrics.strengths = heuristic.strengths
        if not metrics.weaknesses:
            metrics.weaknesses = heuristic.weaknesses
        if not metrics.market_positioning:
            metrics.market_positioning = heuristic.market_positioning
        return metrics

    def _heuristic_extract(
        self, corpus: List[str], company: str, source_urls: List[str]
    ) -> CompetitorMetrics:
        text = "\n".join(corpus)
        sentences = [s for s in _sentences(text) if not _is_boilerplate(s)]

        pricing = _claim(sentences, _PRICING_PATTERNS, limit=2)
        audience = _claim(
            sentences, _AUDIENCE_PATTERNS, limit=3, exclude=set(pricing)
        )
        value_props = _claim(
            sentences,
            _VALUE_PATTERNS,
            limit=4,
            exclude=set(pricing + audience),
        )
        core_claimed = set(pricing + audience + value_props)

        # Opinion dimensions may reuse sentences already claimed by the core
        # dimensions as a last resort so a thin corpus never yields empties.
        strengths = _claim(
            sentences, _STRENGTH_PATTERNS, limit=3, prefer_unclaimed=core_claimed
        )
        weaknesses = _claim(
            sentences, _WEAKNESS_PATTERNS, limit=3, prefer_unclaimed=core_claimed
        )
        competitors = _claim(
            sentences, _COMPETITOR_PATTERNS, limit=4, prefer_unclaimed=core_claimed
        )
        positioning = _claim(
            sentences, _POSITIONING_PATTERNS, limit=2, prefer_unclaimed=core_claimed
        )

        # Clause-level fallback: real web snippets are often one long sentence,
        # so matching on individual clauses captures more signal.
        clauses = _clauses(sentences)
        if not strengths:
            strengths = _claim(clauses, _STRENGTH_PATTERNS, limit=3)
        if not weaknesses:
            weaknesses = _claim(clauses, _WEAKNESS_PATTERNS, limit=3)
        if not competitors:
            competitors = _claim(clauses, _COMPETITOR_PATTERNS, limit=4)
        if not positioning:
            positioning = _claim(clauses, _POSITIONING_PATTERNS, limit=2)

        overview_parts = [
            p for p in (pricing[:1] + audience[:1] + positioning[:1]) if p
        ]
        overview = " ".join(overview_parts[:3])
        if not overview:
            overview = (
                f"{company} operates in a competitive market segment. "
                "Automated research was performed; see the pricing and "
                "audience fields below."
            )

        return CompetitorMetrics(
            company_overview=overview,
            pricing_model="; ".join(pricing) if pricing else None,
            target_audience="; ".join(audience) if audience else None,
            key_value_propositions=value_props,
            competitors_mentioned=competitors,
            strengths=strengths,
            weaknesses=weaknesses,
            market_positioning="; ".join(positioning) if positioning else None,
            recent_news=[],
            source_urls=source_urls,
        )


# --------------------------------------------------------------------------- #
# 3. Evaluator
# --------------------------------------------------------------------------- #
class EvaluatorNode:
    """Scores research quality in ``[0.0, 1.0]`` and writes retry feedback.

    Scoring is deterministic and weights the essential market-research dimensions most:
    pricing and target audience are the heaviest signals, followed by value
    propositions and sourcing. When the score drops below the configured
    threshold, ``feedback`` names the missing dimensions with concrete search
    hints that the researcher turns back into queries.
    """

    SCORE_WEIGHTS = {
        "company_overview": 0.10,
        "pricing_model": 0.25,
        "target_audience": 0.25,
        "key_value_propositions": 0.15,
        "strengths": 0.05,
        "weaknesses": 0.05,
        "market_positioning": 0.05,
        "source_urls": 0.10,
    }

    FIELD_LABELS = {
        "company_overview": "company overview",
        "pricing_model": "pricing",
        "target_audience": "target audience",
        "key_value_propositions": "value propositions",
        "strengths": "strengths",
        "weaknesses": "weaknesses",
        "market_positioning": "market positioning",
        "source_urls": "source URLs",
    }

    HINTS = {
        "company overview": "Re-run a broad overview query and include the "
        "company description.",
        "pricing": "Re-run targeted pricing queries (plans, tiers, price "
        "points, discounts, annual billing).",
        "target audience": "Re-run target audience queries (buyers, "
        "customers, demographics, segments).",
        "value propositions": "Re-run value-proposition queries (features, "
        "benefits, differentiators).",
        "strengths": "Re-run strengths / review-rating queries.",
        "weaknesses": "Re-run weaknesses / criticism / cons queries.",
        "market positioning": "Re-run market-positioning queries (analyst "
        "reports, market share).",
        "source URLs": "Broaden the search and keep more source URLs.",
    }

    @staticmethod
    def _present(field_value: Any) -> float:
        if isinstance(field_value, str):
            return 1.0 if field_value.strip() else 0.0
        if isinstance(field_value, list):
            return min(1.0, len(field_value) / 2.0)
        return 0.0

    def _build_feedback(self, missing: List[str]) -> str:
        if not missing:
            return ""
        lines = [
            "Research is incomplete. The following essential dimensions are "
            "missing or under-sourced:",
        ]
        lines.extend(f"- {label}: {self.HINTS[label]}" for label in missing)
        return "\n".join(lines)

    def __call__(self, state: AgentState) -> dict:
        metrics = state.get("structured_insights")
        if metrics is None:
            return {"quality_score": 0.0, "feedback": "No structured insights produced."}

        score = sum(
            weight * self._present(getattr(metrics, field))
            for field, weight in self.SCORE_WEIGHTS.items()
        )
        # feedback exists only to steer a retry; once the score clears the
        # threshold the research is adequate and no retry guidance is needed.
        if score >= QUALITY_THRESHOLD:
            return {"quality_score": round(score, 3), "feedback": ""}

        missing = [
            label
            for field, label in self.FIELD_LABELS.items()
            if self._present(getattr(metrics, field)) < 0.5
        ]
        return {
            "quality_score": round(score, 3),
            "feedback": self._build_feedback(missing),
        }


# --------------------------------------------------------------------------- #
# 4. Human approval gate
# --------------------------------------------------------------------------- #
class HumanApprovalNode:
    """Validation gate before the human-in-the-loop checkpoint.

    Runs immediately before the ``interrupt_before=["drafter"]`` checkpoint.
    At this point the graph halts so an operator can review the synthesized
    insights and approve/reject before any report is drafted. A rejected
    approval short-circuits to ``END`` via a conditional edge; approval is
    injected back into state with ``graph.update_state`` before resuming.
    """

    def __call__(self, state: AgentState) -> dict:
        if state.get("structured_insights") is None:
            raise ValueError(
                "human_approval reached without structured_insights — "
                "graph routing is misconfigured."
            )
        # No state mutation: the operator decision is applied externally via
        # `update_state`, and the actual pause is the interrupt_before edge.
        return {}


# --------------------------------------------------------------------------- #
# 5. Drafter
# --------------------------------------------------------------------------- #
class DrafterNode:
    """Drafts the approved market intelligence report and outreach email.

    Uses ``llm.with_structured_output(OutreachDraft)`` when configured, or a
    deterministic markdown/email template in offline mode. Requires
    ``human_approved is True``; otherwise it emits an explicit rejection
    artifact instead of a report.
    """

    def __init__(self, llm: Optional[Any] = None) -> None:
        """Args: llm: chat model supporting ``with_structured_output``."""
        self.llm = llm

    def __call__(self, state: AgentState) -> dict:
        company: str = state["target_company"]
        metrics: CompetitorMetrics = state["structured_insights"]

        if not state.get("human_approved"):
            return {
                "final_report": json.dumps(
                    {
                        "status": "rejected",
                        "message": (
                            "Human-in-the-loop approval was not granted; "
                            "no report was drafted. Resume the thread with "
                            "`python main.py resume --approve` to continue."
                        ),
                    },
                    indent=2,
                )
            }

        outreach = (
            self._llm_draft(state, metrics)
            if self.llm is not None
            else self._template_draft(state, metrics)
        )

        research_queries = sorted(
            {item.get("query", "") for item in state.get("raw_search_data", []) if item.get("query")}
        )

        report = ResearchReport(
            target_company=company,
            metrics=metrics,
            research_queries=research_queries,
            iteration_count=state.get("iteration_count", 0),
            quality_score=state.get("quality_score", 0.0),
            feedback=state.get("feedback", ""),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        final = {
            "research_report": report.model_dump(),
            "outreach_draft": outreach.model_dump(),
        }
        return {"final_report": json.dumps(final, indent=2, ensure_ascii=False)}

    def _llm_draft(self, state: AgentState, metrics: CompetitorMetrics) -> OutreachDraft:
        system = SystemMessage(
            content=(
                "You are a senior market-intelligence strategist. Based on the "
                "approved competitive research, produce an executive "
                "intelligence report (markdown), a concise outreach email, and "
                "3 recommended follow-up plays. The email must sound like a real "
                "person, reference the researched findings, and end with one "
                "low-friction call to action."
            )
        )
        payload = {
            "target_company": state["target_company"],
            "quality_score": state.get("quality_score", 0.0),
            "iteration_count": state.get("iteration_count", 0),
            "metrics": metrics.model_dump(),
        }
        human = HumanMessage(content=json.dumps(payload, indent=2))

        structured = self.llm.with_structured_output(OutreachDraft, method="function_calling")
        raw = structured.invoke([system, human])
        if isinstance(raw, OutreachDraft):
            return raw
        if isinstance(raw, dict):
            return OutreachDraft.model_validate(raw)
        return OutreachDraft.model_validate_json(str(raw))

    def _template_draft(self, state: AgentState, metrics: CompetitorMetrics) -> OutreachDraft:
        company: str = state["target_company"]
        score: float = state.get("quality_score", 0.0)
        iterations: int = state.get("iteration_count", 0)
        vps = metrics.key_value_propositions or ["a faster time-to-value"]
        hook = vps[0]

        summary = "\n".join(
            [
                f"# Market Intelligence Report: {company}",
                "",
                f"*Quality score: {score:.2f} | Self-correction loops: {iterations}*",
                "",
                "## Company Overview",
                metrics.company_overview or "No overview captured.",
                "",
                "## Pricing Model",
                metrics.pricing_model or "Not identified in the research.",
                "",
                "## Target Audience",
                metrics.target_audience or "Not identified in the research.",
                "",
                "## Key Value Propositions",
                *[f"- {vp}" for vp in vps],
                "",
                "## Strengths",
                *[f"- {s}" for s in (metrics.strengths or ["Not identified."])],
                "",
                "## Weaknesses",
                *[f"- {w}" for w in (metrics.weaknesses or ["Not identified."])],
                "",
                "## Market Positioning",
                metrics.market_positioning or "Not identified in the research.",
                "",
                "## Sources",
                *[f"- {u}" for u in metrics.source_urls[:10]],
            ]
        )

        pricing_line = metrics.pricing_model or "Their pricing signals look flexible"
        email = "\n".join(
            [
                f"Subject: Idea for {company} — {hook}",
                "",
                f"Hi {{first_name}},",
                "",
                f"I've been researching how brands like {{{{company}}}} are approaching "
                f"the current market, and one pattern stood out: {hook}.",
                "",
                f"Pricing-wise, {pricing_line}. The feedback I read points to "
                "strong customer attention.",
                "",
                "I put together a short, 2-minute brief tailored to your category. "
                "Open to taking a look?",
                "",
                "Best,",
                "{{sender_name}}",
            ]
        )

        follow_ups = [
            f'Follow-up 1 (Day 3): share a one-pager on "{hook}" and how it maps to their industry.',
            "Follow-up 2 (Day 7): offer a 15-min gap analysis vs their current tooling.",
            "Follow-up 3 (Day 14): share a case study from a comparable mid-market account.",
        ]

        return OutreachDraft(
            intelligence_summary=summary,
            cold_outreach_email=email,
            recommended_follow_ups=follow_ups,
        )
