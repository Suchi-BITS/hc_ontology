"""OpenAI LLM and embedding helpers (LangChain + OpenAI SDK)."""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI

from core.config import get_settings
from core.ssl_config import configure_ssl

configure_ssl()


def _api_key() -> str:
    return get_settings().get("openai_api_key") or ""


def require_api_key() -> str:
    key = _api_key()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. It is required for natural-language queries, "
            "embeddings, GraphRAG and the agent (OpenAI). Copy .env.example to .env and "
            "set OPENAI_API_KEY, or export it in the environment. "
            "See docs/security-and-configuration.md."
        )
    return key


@lru_cache
def get_openai_client() -> OpenAI:
    return OpenAI(api_key=require_api_key(), http_client=httpx.Client(timeout=120.0))


def get_chat_llm(*, temperature: float = 0, model: str | None = None) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=model or settings["llm_model"],
        temperature=temperature,
        api_key=_api_key() or None,
        http_client=httpx.Client(timeout=120.0),
        http_async_client=httpx.AsyncClient(timeout=120.0),
    )


@lru_cache
def get_embeddings_client() -> OpenAIEmbeddings:
    settings = get_settings()
    kwargs: dict = {
        "model": settings["embedding_model"],
        "api_key": _api_key() or None,
    }
    model = settings["embedding_model"]
    dims = int(settings.get("embedding_dimensions") or 0)
    if dims > 0 and "text-embedding-3" in model:
        kwargs["dimensions"] = dims
    return OpenAIEmbeddings(**kwargs)


def embed_text(text: str) -> list[float]:
    return get_embeddings_client().embed_query(text or "")


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    return get_embeddings_client().embed_documents(list(texts))
