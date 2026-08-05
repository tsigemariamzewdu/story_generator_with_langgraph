"""Search-tool factory with a deterministic offline mock fallback.

The researcher node never talks to a search provider directly; it consumes
any callable with the signature ``(query: str) -> list[dict]``. This module
builds the most capable tool available in the environment:

1. **Tavily** — used when ``TAVILY_API_KEY`` is set.
2. **Serper.dev (Google)** — used when ``SERPER_API_KEY`` is set.
3. **Mock search** — deterministic, offline fallback so the whole pipeline
   runs without API keys (clearly flagged via ``is_mock: True``).

Every provider output is normalised to the same record shape::

    {"title": str, "url": str, "content": str,
     "source": str, "is_mock": bool}
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Dict, List

from config import SEARCH_RESULTS_PER_QUERY

logger = logging.getLogger(__name__)


def build_search_tool() -> Callable[[str], List[dict]]:
    """Return the best search tool available, falling back to the mock."""

    if os.getenv("TAVILY_API_KEY"):
        try:
            return _build_tavily()
        except Exception:
            logger.warning("Tavily search init failed, falling back.", exc_info=True)

    if os.getenv("SERPER_API_KEY"):
        try:
            return _build_serper()
        except Exception:
            logger.warning("Serper search init failed, falling back.", exc_info=True)

    return mock_web_search


# --------------------------------------------------------------------------- #
# Tavily
# --------------------------------------------------------------------------- #
def _build_tavily() -> Callable[[str], List[dict]]:
    import requests

    api_key = os.getenv("TAVILY_API_KEY")
    url = "https://api.tavily.com/search"

    def _search(query: str) -> List[dict]:
        resp = requests.post(
            url,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": SEARCH_RESULTS_PER_QUERY,
            },
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("url", "")),
                "content": str(r.get("content", r.get("raw_content", ""))),
                "source": "tavily",
                "is_mock": False,
            }
            for r in results
        ]

    return _search


# --------------------------------------------------------------------------- #
# Serper.dev
# --------------------------------------------------------------------------- #
def _build_serper() -> Callable[[str], List[dict]]:
    import requests

    api_key = os.getenv("SERPER_API_KEY")
    url = "https://google.serper.dev/search"

    def _search(query: str) -> List[dict]:
        resp = requests.post(
            url,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": SEARCH_RESULTS_PER_QUERY},
            timeout=30,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic", [])
        return [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("link", "")),
                "content": str(r.get("snippet", "")),
                "source": "serper",
                "is_mock": False,
            }
            for r in organic
        ]

    return _search


# --------------------------------------------------------------------------- #
# Mock search (offline fallback)
# --------------------------------------------------------------------------- #
_MOCK_TEMPLATES: Dict[str, List[str]] = {
    "pricing": [
        "{company} appears to use a tiered pricing structure with entry, "
        "growth, and enterprise options. Public pricing details vary by plan "
        "and buying channel.",
        "Pricing review: {company} may offer monthly or annual billing, with "
        "higher-touch plans reserved for larger deployments.",
        "Compared with other options in its category, {company} seems to "
        "emphasize flexibility, packaging, and the total cost of ownership.",
    ],
    "audience": [
        "The target audience appears to include mainstream buyers who care "
        "about brand, price, and product experience.",
        "{company} likely serves a mix of value-conscious customers and "
        "premium buyers depending on the product line.",
        "Buyers evaluating {company} are typically comparing style, quality, "
        "availability, and the overall customer experience.",
    ],
    "value": [
        "Key value proposition: {company} appears to compete on a mix of "
        "brand strength, product quality, and customer trust.",
        "Customers may value {company}'s design, selection, convenience, or "
        "performance depending on the category.",
        "{company} differentiates by balancing premium perception with broad "
        "market reach and strong recognition.",
    ],
    "competitors": [
        "In the competitive landscape, {company} is compared with direct "
        "category peers, lower-priced alternatives, and premium substitutes.",
        "Market share analysis: {company} competes with established incumbents "
        "and fast-growing challengers in its category.",
    ],
    "positioning": [
        "Analyst notes position {company} as a well-known brand with strong "
        "consumer awareness and category relevance.",
        "Market commentary describes {company} as a major player that wins on "
        "recognition, scale, and distribution.",
    ],
    "strengths": [
        "Strengths cited by reviewers include strong brand recognition, wide "
        "availability, and consistent product visibility.",
        "Customers highlight {company}'s ability to stay top-of-mind and "
        "maintain a clear market identity.",
    ],
    "weaknesses": [
        "Common criticism: premium pricing or crowded category positioning may "
        "limit conversion among more price-sensitive buyers.",
        "Weaknesses noted in reviews include uneven availability, limited "
        "differentiation in crowded segments, or high expectations at scale.",
    ],
    "news": [
        "Recent news: {company} continues to invest in product launches, "
        "campaigns, and channel expansion.",
        "{company} has recent coverage around new releases, partnerships, or "
        "seasonal market activity.",
    ],
}

_TOPIC_KEYWORDS = [
    ("pricing", ("pricing", "cost", "plan", "per user", "per month", "tier", "trial")),
    ("audience", ("audience", "customer", "buyer", "icp", "b2b", "smb", "enterprise", "segment")),
    ("value", ("value proposition", "value prop", "benefit", "integrat", "automation", "roi", "differentiat")),
    ("competitors", ("competitor", "vs", "alternative", "landscape", "market share")),
    ("positioning", ("position", "gartner", "magic quadrant", "market share")),
    ("strengths", ("strength", "leader", "best-in-class", "award")),
    ("weaknesses", ("weakness", "criticism", "limitation", "downside")),
    ("news", ("news", "announced", "raise", "launch")),
]

_MOCK_HOSTS = [
    "https://www.g2.com/products/example/reviews",
    "https://www.capterra.com/p/example",
    "https://www.saasworthy.com/review/example",
    "https://techcrunch.com/2026/02/example-funding",
    "https://www.trustradius.com/products/example/reviews",
]


def mock_web_search(query: str) -> List[dict]:
    """Deterministic offline search that mimics real provider output.

    The query is parsed to pick relevant topic templates, so pricing queries
    produce pricing snippets and audience queries produce audience snippets.
    All records are flagged ``is_mock: True``.
    """

    company = _extract_company(query)
    lowered = query.lower()
    topics = [
        topic
        for topic, keywords in _TOPIC_KEYWORDS
        if any(kw in lowered for kw in keywords)
    ] or ["generic"]

    results: List[dict] = []
    for i, topic in enumerate(topics[:3]):
        pool = _MOCK_TEMPLATES.get(topic) or _MOCK_TEMPLATES["news"]
        content = pool[i % len(pool)].format(company=company)
        slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
        results.append(
            {
                "title": f"{company}: {topic.replace('_', ' ').title()} research",
                "url": f"{_MOCK_HOSTS[i % len(_MOCK_HOSTS)]}/{slug}?q={topic}",
                "content": content,
                "source": "mock-web",
                "is_mock": True,
            }
        )
    return results


def _extract_company(query: str) -> str:
    """Best-effort pull of the company name from a researcher query."""

    stops = (
        " strengths weaknesses market position",
        " strengths weaknesses",
        " advantages compared with competitors",
        " advantages compared with",
        " benefits features differentiators",
        " pricing model plans",
        " target audience customers buyers market",
        " pricing plans cost per user",
        " value proposition vs competitors",
        " value proposition competitors",
        " target audience ideal customer",
        " weaknesses limitations criticism",
        " market position analyst report",
        " strengths reviews ratings",
        " latest news press release",
        " pricing",
        " target audience",
        " value proposition",
        " latest news",
        " strengths",
        " weaknesses",
        " competitors",
        " position",
    )
    # Longest, most specific markers first so the company name is cut at the
    # most precise boundary.
    for stop in sorted(stops, key=len, reverse=True):
        idx = query.lower().find(stop)
        if idx > 0:
            return query[:idx].strip()
    return query.split(" ")[0].strip() if query else "Unknown Company"
