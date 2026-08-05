"""Centralised environment configuration and LLM factory.

Reading everything from ``.env`` (or the process environment) keeps the
pipeline provider-agnostic. ``LLM_MODEL`` uses LangChain's ``<provider>:<model>``
convention, e.g. ``google_genai:gemini-2.5-flash`` or ``openai:gpt-4o``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()  # fall back to any ambient environment

# -- Pipeline tuning ------------------------------------------------------- #
QUALITY_THRESHOLD: float = float(os.getenv("QUALITY_THRESHOLD", "0.8"))
MAX_RESEARCH_ITERATIONS: int = int(os.getenv("MAX_RESEARCH_ITERATIONS", "3"))
SEARCH_RESULTS_PER_QUERY: int = int(os.getenv("SEARCH_RESULTS_PER_QUERY", "5"))

# -- LLM ------------------------------------------------------------------- #
DEFAULT_MODEL: str = os.getenv("LLM_MODEL", "google_genai:gemini-2.5-flash")

_PROVIDER_KEYS: dict[str, Optional[str]] = {
    "openai": "OPENAI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "ollama": None,
}


def has_llm_config() -> bool:
    """Return ``True`` if a usable API key exists for the configured model."""

    provider = DEFAULT_MODEL.split(":", 1)[0]
    key_var = _PROVIDER_KEYS.get(provider, "OPENAI_API_KEY")
    return key_var is None or bool(os.getenv(key_var))


def has_search_config() -> bool:
    """Return ``True`` if a live web-search provider is configured."""

    return bool(os.getenv("TAVILY_API_KEY") or os.getenv("SERPER_API_KEY"))


def get_llm(model: Optional[str] = None, temperature: float = 0.0):
    """Build a LangChain chat model for the configured provider.

    Args:
        model: optional ``<provider>:<model>`` override (defaults to
            ``LLM_MODEL``).
        temperature: sampling temperature (``0`` for deterministic
            structured extraction).

    Returns:
        A ``ChatModel`` runnable supporting ``with_structured_output``.
    """

    from langchain.chat_models import init_chat_model

    model = model or DEFAULT_MODEL
    provider = model.split(":", 1)[0] if ":" in model else None
    key_var = _PROVIDER_KEYS.get(provider, "OPENAI_API_KEY") if provider else None

    kwargs: dict = {"model": model, "temperature": temperature}
    if key_var and os.getenv(key_var):
        kwargs["api_key"] = os.getenv(key_var)

    return init_chat_model(**kwargs)
