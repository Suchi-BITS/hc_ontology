"""Unit tests for four-memory subsystem (no Neo4j/Ollama required)."""

from agents.memory.meta_memory import RecallPlan, format_scored_turns, score_turn
from agents.memory.working import append_working_event, compact_working_context
from agents.nodes.memory_load import memory_load_node


def test_score_turn_prefers_relevant_completed():
    high = score_turn(
        {
            "question": "List patients with diabetes",
            "status": "completed",
            "confidence": 0.9,
            "validated_query": "MATCH (p:Patient)...",
            "created_at": "2026-09-01T12:00:00+00:00",
        },
        "Show diabetes patients",
    )
    low = score_turn(
        {
            "question": "What is the weather?",
            "status": "failed",
            "confidence": 0.1,
            "created_at": "2026-08-01T12:00:00+00:00",
        },
        "Show diabetes patients",
    )
    assert high > low


def test_format_scored_turns_includes_scores():
    text = format_scored_turns(
        [{"question": "Q1", "answer": "A1", "status": "completed", "_meta_score": 0.82}]
    )
    assert "score=0.82" in text
    assert "Q1" in text


def test_recall_plan_to_dict_omits_internal_turns():
    plan = RecallPlan(scored_turns=[{"turn_id": "t1"}])
    data = plan.to_dict()
    assert "scored_turns" not in data
    assert data["episodic_limit"] == 5


def test_compact_working_context_prioritizes_question():
    text = compact_working_context(
        question="List patients with diabetes",
        memory_bundle={
            "episodic": {"recent_text": "Prior Q about doctors"},
            "procedural": [{"name": "patients_diabetes", "template_query": "MATCH (p:Patient)...", "match_score": 0.9}],
            "semantic": {"concepts": [{"name": "Patient"}, {"name": "Diagnosis"}]},
        },
        max_chars=6000,
    )
    assert "List patients with diabetes" in text
    assert "patients_diabetes" in text
    assert "Patient" in text


def test_compact_working_context_respects_max_chars():
    text = compact_working_context(
        question="x" * 5000,
        memory_bundle={"episodic": {"recent_text": "y" * 5000}},
        max_chars=100,
    )
    assert len(text) <= 100


def test_append_working_event():
    events = append_working_event([], "test", {"k": 1})
    assert len(events) == 1
    assert events[0]["type"] == "test"
    assert events[0]["payload"]["k"] == 1


def test_memory_load_node_without_session():
    out = memory_load_node({"question": "What is Hypertension?", "trace": [], "errors": []})
    assert "memory_bundle" in out
    assert "working_context" in out
    assert "meta_memory" in out
    assert out["trace"][0] == "memory_load:start"
