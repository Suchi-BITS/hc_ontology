"""Governance: abstention, provenance, retrieval pipeline, structured responses."""

from enterprise.abstention import compute_confidence, decide_abstention
from enterprise.provenance import build_provenance
from enterprise.retrieval_pipeline import compute_error_budget, rerank_candidates
from enterprise.structured_response import build_structured_answer, parse_llm_structured


def test_provenance_requires_query_and_results_for_cypher():
    state = {
        "query_type": "cypher",
        "validated_query": "MATCH (p:Patient) RETURN p",
        "results": [{"name": "Alice"}],
        "retrieved_concepts": [{"name": "Patient", "score": 0.2}],
    }
    prov = build_provenance(state)
    assert prov["mandatory_satisfied"] is True
    assert prov["has_query_path"] is True
    assert prov["result_count"] == 1


def test_provenance_fails_without_results():
    state = {
        "query_type": "cypher",
        "validated_query": "MATCH (p:Patient) RETURN p",
        "results": [],
    }
    prov = build_provenance(state)
    assert prov["mandatory_satisfied"] is False


def test_abstention_refuses_low_confidence():
    state = {
        "query_type": "cypher",
        "validated_query": "MATCH (n) RETURN n LIMIT 1",
        "results": [],
        "retrieved_concepts": [],
        "validation_ok": True,
    }
    decision = decide_abstention(state, threshold=0.9)
    assert decision["refused"] is True
    assert decision["refusal_reason"] in ("low_confidence", "missing_provenance")


def test_abstention_allows_ontology_only_with_concepts():
    state = {
        "query_type": "ontology_only",
        "results": [{"name": "Diagnosis", "score": 0.5}],
        "retrieved_concepts": [{"name": "Diagnosis", "rrf_score": 0.4, "source": "vector"}],
        "validation_ok": True,
    }
    decision = decide_abstention(state, threshold=0.3)
    assert decision["refused"] is False
    assert decision["confidence"] >= 0.3


def test_rerank_prefers_lexical_match():
    question = "List patients with diabetes"
    pool = [
        {"name": "Hospital", "rrf_score": 0.5, "description": "facility"},
        {"name": "Patient", "rrf_score": 0.2, "description": "person with care"},
    ]
    ranked = rerank_candidates(question, pool, top_k=2)
    assert ranked[0]["name"] == "Patient"
    assert "rerank_score" in ranked[0]


def test_error_budget_reports_pool_metrics():
    budget = compute_error_budget(
        "diabetes patient medication",
        pool=[{"name": "Patient"}, {"name": "Diagnosis"}],
        reranked=[{"name": "Patient", "rerank_score": 0.6}],
        channels={"vector": [{}], "graph": []},
    )
    assert budget["pool_size"] == 2
    assert "residual_retrieval_risk" in budget


def test_structured_answer_refused_shape():
    payload = build_structured_answer(
        question="q",
        query_type="cypher",
        query="MATCH (n) RETURN n",
        results=[],
        concepts=[],
        refused=True,
        refusal_reason="low_confidence",
        confidence=0.2,
        summary="refused",
    )
    assert payload["status"] == "refused"
    assert payload["facts"] == []
    assert payload["refusal_reason"] == "low_confidence"


def test_parse_llm_structured_extracts_json():
    raw = 'Here is output:\n{"status": "answered", "summary": "ok", "confidence": 0.9}'
    data = parse_llm_structured(raw)
    assert data == {"status": "answered", "summary": "ok", "confidence": 0.9}


def test_agent_graph_includes_abstention_node():
    from agents.graph import build_agent_graph

    graph = build_agent_graph()
    node_ids = set(graph.get_graph().nodes.keys())
    assert "abstention" in node_ids
