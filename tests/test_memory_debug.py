"""Tests for memory debug context logging."""

from agents.memory.debug_context import (
    log_memory_phase,
    memory_debug_enabled,
    snapshot_from_state,
    snapshot_query_grounding,
    snapshot_recall_plan,
)


def test_snapshot_from_state_shapes_memory_fields():
    snap = snapshot_from_state(
        {
            "question": "List patients with diabetes",
            "session_id": "s1",
            "memory_bundle": {
                "episodic": {
                    "recent_text": "Prior Q/A",
                    "similar_episodes": [{"question": "old q", "validated_query": "MATCH (p) RETURN p"}],
                },
                "procedural": [
                    {
                        "name": "patients_diabetes",
                        "match_score": 0.9,
                        "template_query": "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d) RETURN p",
                    }
                ],
                "semantic": {"concepts": [{"name": "Patient"}]},
            },
            "working_context": "### Question\nList patients",
            "meta_memory": {"recall_confidence": 0.8, "episodic_limit": 5},
        }
    )
    assert snap["question"] == "List patients with diabetes"
    assert snap["episodic"]["similar_count"] == 1
    assert snap["procedural"][0]["name"] == "patients_diabetes"
    assert "template_query" in snap["procedural"][0]
    assert "Patient" in snap["semantic"]["concepts"]


def test_repair_context_detected_in_grounding_snapshot():
    snap = snapshot_query_grounding(
        {
            "question": "Find patients on fake drug",
            "validation_error": "Unknown relationship",
            "draft_query": "MATCH (p)-[:ON_FAKE]->(x) RETURN p",
            "memory_bundle": {},
        },
        grounded="### Repair context\nPrevious query failed:\nMATCH ...",
        procedure_reused=False,
    )
    assert snap["repair_context"]["present"] is True
    assert snap["procedure_template_reused"] is False


def test_snapshot_recall_plan_truncates_summary(monkeypatch):
    monkeypatch.setenv("MEMORY_DEBUG_CONTEXT_FULL", "false")
    from core.config import get_settings

    get_settings.cache_clear()
    class _Plan:
        def to_dict(self):
            return {
                "recall_confidence": 0.7,
                "session_summary": "x" * 1000,
                "signals": {"scored_turns": [{"turn_id": "t1", "score": 0.8}]},
            }

    plan = snapshot_recall_plan(_Plan())
    assert len(plan["session_summary"]) < 1000
    assert plan["signals"]["scored_turns"][0]["turn_id"] == "t1"


def test_log_memory_phase_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("MEMORY_DEBUG_CONTEXT", "false")
    from core.config import get_settings

    get_settings.cache_clear()
    assert memory_debug_enabled() is False
    log_memory_phase("test", question="q", before={"k": 1})  # should not raise
