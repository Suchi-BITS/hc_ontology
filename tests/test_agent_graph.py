"""Smoke tests for multi-agent graph wiring (no Ollama/Neo4j required)."""

from agents.graph import build_agent_graph, serialize_state
from agents.nodes.validation import route_after_validation
from agents.nodes.human_gate import route_after_human
from agents.nodes.planner import _heuristic_plan, _parse_json


def test_heuristic_plan_defaults_to_cypher():
    plan = _heuristic_plan("List patients with diabetes")
    assert plan["query_type"] == "cypher"
    assert isinstance(plan["plan"], list)
    assert len(plan["plan"]) >= 3


def test_heuristic_plan_sparql_keyword():
    plan = _heuristic_plan("Write a SPARQL query for Diagnosis")
    assert plan["query_type"] == "sparql"


def test_heuristic_plan_ontology_only():
    plan = _heuristic_plan("What is the meaning of Hypertension concept?")
    assert plan["query_type"] == "ontology_only"


def test_parse_json_from_markdown():
    raw = '```json\n{"query_type": "cypher", "require_human_approval": false, "reasoning": "x", "plan": ["a"]}\n```'
    data = _parse_json(raw)
    assert data["query_type"] == "cypher"


def test_route_after_validation_retry():
    assert (
        route_after_validation(
            {
                "validation_ok": False,
                "query_attempts": 1,
                "max_retries": 3,
            }
        )
        == "retry_query"
    )
    assert (
        route_after_validation(
            {
                "validation_ok": False,
                "query_attempts": 3,
                "max_retries": 3,
            }
        )
        == "respond_failed"
    )
    assert route_after_validation({"validation_ok": True}) == "human_gate"


def test_route_after_human():
    assert route_after_human({"human_decision": "rejected"}) == "rejected"
    assert route_after_human({"human_decision": "approved"}) == "execution"


def test_build_agent_graph_compiles():
    graph = build_agent_graph()
    assert graph is not None
    # Compiled graph exposes nodes via get_graph
    g = graph.get_graph()
    node_ids = set(g.nodes.keys())
    for name in (
        "planner",
        "ontology",
        "query",
        "validation",
        "human_gate",
        "execution",
        "response",
    ):
        assert name in node_ids


def test_serialize_state_truncates_results():
    values = {
        "question": "q",
        "results": list(range(60)),
        "ontology_context": "x" * 5000,
    }
    out = serialize_state(values)
    assert len(out["results"]) == 50
    assert out.get("results_truncated") is True
    assert out["ontology_context"].endswith("…")
