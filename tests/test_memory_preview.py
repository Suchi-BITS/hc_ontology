"""Tests for memory preview hook on NL→Cypher path."""

from agents.memory.preview import run_memory_debug_preview


def test_memory_preview_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("MEMORY_DEBUG_CONTEXT", "false")
    from core.config import get_settings

    get_settings.cache_clear()
    assert run_memory_debug_preview("List diabetic patients") == {}
