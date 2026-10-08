"""Enterprise capability unit tests (no external services required)."""

from enterprise.cost import CostTracker
from enterprise.evaluation import EvalCase, run_evaluation
from enterprise.guardrails import check_input, check_output
from enterprise.ontology_registry import ontology_registry
from enterprise.rbac import Permission, ROLE_PERMISSIONS
from enterprise.tenancy import tenant_registry


def test_guardrails_block_dangerous_input():
    r = check_input("Please DETACH DELETE everything")
    assert r.allowed is False


def test_guardrails_allow_normal_question():
    r = check_input("List patients with diabetes")
    assert r.allowed is True


def test_guardrails_redact_pii():
    r = check_input("Call me at 415-555-1212 about diabetes")
    assert r.allowed is True
    assert r.redacted_text == "Call me at [REDACTED] about diabetes"
    assert "pii" in r.flags


def test_guardrails_block_dangerous_output():
    r = check_output("You should run DETACH DELETE n")
    assert r.allowed is False


def test_tenants_seeded():
    assert tenant_registry.get("default").ontology_ids == ["hc-core"]
    assert tenant_registry.get("research").ontology_ids == ["hc-core", "hc-research"]


def test_ontology_registry_versions():
    rec = ontology_registry.get("hc-core")
    assert rec.active_version == "1.0.0"
    path, ver = ontology_registry.resolve_owl_path("hc-core")
    assert ver.version == "1.0.0"
    from pathlib import Path

    assert Path(path).name == "healthcare_schema.ttl" and Path(path).is_file()


def test_rbac_admin_has_all():
    perms = ROLE_PERMISSIONS["admin"]
    assert Permission.ADMIN in perms
    assert Permission.AGENT_APPROVE in perms


def test_cost_budget():
    tracker = CostTracker()
    tracker.record("t1", "agent_run", units=1)
    assert tracker.day_spend("t1") > 0
    assert tracker.within_budget("t1", 100.0) is True
    assert tracker.within_budget("t1", 0.0) is False


def test_eval_offline_runner():
    from agents.nodes.planner import _heuristic_plan

    def runner(case: EvalCase):
        g = check_input(case.question)
        if not g.allowed:
            return {"status": "failed", "blocked": True, "answer": g.reason}
        plan = _heuristic_plan(case.question)
        return {"status": "completed", "query_type": plan["query_type"], "answer": "ok"}

    report = run_evaluation(runner)
    assert report["cases"] == 5
    # The stub runner classifies and blocks correctly but never refuses for low evidence:
    assert report["passed"] == 4 and report["split"] == "all"
    assert 0.0 < report["avg_score"] < 1.0
