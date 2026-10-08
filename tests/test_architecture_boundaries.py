"""CORE vs ADVANCED: the semantic foundation must stand without the AI layer.

Three kinds of evidence, each independent of the others:

1. static   - an import-graph analysis of every module (eager and lazy imports);
2. runtime  - a fresh interpreter in which openai, langchain, langgraph, langsmith, opentelemetry, streamlit
              and the neo4j driver CANNOT be imported, running the real API and the real validators;
3. packaging - requirements-core.txt is a subset of requirements.txt and names no AI package.

See docs/core-vs-ai-architecture.md.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

AI_LIBS = {"openai", "langchain", "langchain_core", "langchain_openai", "langgraph", "langsmith", "opentelemetry", "streamlit"}
NEO4J_DRIVER = {"neo4j"}

# ---- the classification: one place, reviewed like code ------------------------------------------------
ADVANCED_PREFIXES = ("agents", "enterprise", "streamlit_app")
ADVANCED_MODULES = {
    "core.llm", "services.cypher_generator", "services.sparql_generator", "services.embedding_service",
    "services.document_ingestor", "routers.agent", "routers.enterprise", "routers.embedding", "routers.documents",
}
# Core modules that talk to a Neo4j server by design (writing the projection, translating to Cypher, seeding).
NEEDS_NEO4J_DRIVER = {
    "services.neo4j_exporter", "services.sparql_to_cypher", "services.seed_demo_data", "core.dependencies",
    "routers.neo4j", "routers.sparql", "routers.system", "routers.ontology", "routers.patients", "routers.doctors",
    "routers.clinical", "routers.shacl", "api",
}
# The only places where core code may reach into the advanced layer, and always lazily (inside a function).
ALLOWED_LAZY_CORE_TO_ADVANCED = {
    ("api", "routers.agent"), ("api", "routers.documents"), ("api", "routers.embedding"), ("api", "routers.enterprise"),
    ("api", "enterprise.observability"),                       # startup hook; opentelemetry is imported lazily inside it
    ("core.dependencies", "services.cypher_generator"),         # composition root: natural language -> Cypher
    ("core.dependencies", "services.sparql_generator"),         # composition root: natural language -> SPARQL
    ("core.dependencies", "services.embedding_service"),        # composition root: embeddings
    ("services.load_ontology", "core.llm"),                     # generate_sparql(): the one LLM call in the ontology service
    ("services.seed_demo_data", "agents.memory.bootstrap"),     # demo seeding also seeds procedural memory
    ("routers.neo4j", "agents.memory.preview"),                 # memory debug preview on /nl-to-cypher
}


def is_advanced(module: str) -> bool:
    return module in ADVANCED_MODULES or module.startswith(ADVANCED_PREFIXES)


def _modules() -> dict[str, Path]:
    found = {}
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in ("tests", "venv", "k8s", "examples") or "__pycache__" in rel.parts or rel.parts[0].startswith("."):
            continue
        found[".".join(rel.with_suffix("").parts).removesuffix(".__init__")] = path
    return found


MODULES = _modules()
LOCAL_TOP = {m.split(".")[0] for m in MODULES}


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """(eager, lazy) imported dotted names. Lazy = inside a function body."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    eager, lazy = set(), set()

    def visit(node, depth):
        for child in ast.iter_child_nodes(node):
            d = depth + isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            names = []
            if isinstance(child, ast.Import):
                names = [a.name for a in child.names]
            elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
                names = [child.module] + [f"{child.module}.{a.name}" for a in child.names]
            (lazy if d else eager).update(names)
            visit(child, d)

    visit(tree, 0)
    return eager, lazy


IMPORTS = {m: _imports(p) for m, p in MODULES.items()}


def _local(name: str) -> str | None:
    if name.split(".")[0] not in LOCAL_TOP:
        return None
    while name and name not in MODULES:
        name = name.rpartition(".")[0]
    return name or None


def eager_closure(start: str) -> tuple[set[str], set[str]]:
    """(third-party top-level packages, local modules) reached by import-time imports from `start`."""
    seen, stack, third = set(), [start], set()
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        for name in IMPORTS[mod][0]:
            local = _local(name)
            if local:
                stack.append(local)
            else:
                third.add(name.split(".")[0])
    return third, seen


CORE = sorted(m for m in MODULES if not is_advanced(m) and not m.startswith("scripts."))


def test_every_module_is_classified_core_or_advanced():
    """A new module must land on one side deliberately: this list is the architecture."""
    advanced = sorted(m for m in MODULES if is_advanced(m))
    assert {"agents.graph", "enterprise.abstention", "core.llm"} <= set(advanced)
    assert {"core.shacl_validator", "services.graph_projection", "services.load_ontology", "core.sparql_validator"} <= set(CORE)


@pytest.mark.parametrize("module", CORE)
def test_core_module_imports_no_ai_library_at_import_time(module):
    third, _ = eager_closure(module)
    assert not third & AI_LIBS, f"{module} pulls {sorted(third & AI_LIBS)} in at import time"


@pytest.mark.parametrize("module", CORE)
def test_core_module_imports_no_advanced_module_at_import_time(module):
    _, local = eager_closure(module)
    assert not [m for m in local if is_advanced(m)], f"{module} imports {[m for m in local if is_advanced(m)]} eagerly"


def test_lazy_core_to_advanced_edges_are_exactly_the_documented_ones():
    found = set()
    for module in CORE:
        for name in IMPORTS[module][1]:
            target = _local(name)
            if target and is_advanced(target):
                found.add((module, target))
    assert found == ALLOWED_LAZY_CORE_TO_ADVANCED, (
        f"new: {sorted(found - ALLOWED_LAZY_CORE_TO_ADVANCED)}; gone: {sorted(ALLOWED_LAZY_CORE_TO_ADVANCED - found)}")


@pytest.mark.parametrize("module", [m for m in CORE if m not in NEEDS_NEO4J_DRIVER])
def test_validation_path_does_not_need_the_neo4j_driver(module):
    third, _ = eager_closure(module)
    assert not third & NEO4J_DRIVER, f"{module} imports the Neo4j driver at import time"


def test_the_agent_is_a_consumer_of_the_core_never_the_reverse():
    for module in CORE:
        eager, _lazy = IMPORTS[module]
        assert not any(n.split(".")[0] == "agents" for n in eager), module


# ---- runtime: the core really runs with the AI stack unavailable ---------------------------------------

BLOCKER = textwrap.dedent('''
    import importlib.abc, os, sys
    BLOCK = {"openai", "langchain", "langchain_core", "langchain_openai", "langgraph", "langsmith",
             "opentelemetry", "neo4j", "streamlit"}

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in BLOCK:
                raise ImportError("blocked for the test: " + name)

    sys.meta_path.insert(0, Blocker())
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
''')


def run_blocked(body: str, env_extra: dict | None = None) -> dict:
    import os

    code = f"ROOT = {str(ROOT)!r}\n" + BLOCKER + textwrap.dedent(body)
    env = {**os.environ, "ENVIRONMENT": "development", "PYTHONUTF8": "1", **(env_extra or {})}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env, timeout=240)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


API_BODY = '''
    import json
    import api
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    q = "PREFIX hc: <http://example.org/healthcare-hospital.owl#> SELECT ?p WHERE { ?p a hc:Patient }"
    out = {
        "ai_layer_active": api.AI_LAYER_ACTIVE,
        "health": c.get("/health").status_code,
        "sparql": c.post("/sparql", json={"query": q}).json()["results"],
        "projection": c.get("/neo4j/projection").json().get("nodes"),
        "agent_route": c.get("/agent/health").status_code,
        "nl": c.post("/llm-query", json={"question": "list patients"}).status_code,
        "leaked": sorted(m for m in sys.modules if m.split(".")[0] in BLOCK | {"agents"}),
    }
    print(json.dumps(out))
'''


def test_core_api_runs_with_the_whole_ai_stack_and_the_neo4j_driver_unimportable():
    out = run_blocked(API_BODY)
    assert out["health"] == 200
    assert len(out["sparql"]) == 5                    # SPARQL over the RDF answers the competency question
    assert out["projection"] == 124                   # the projection plan needs no database
    assert out["ai_layer_active"] is False            # missing libraries disable the layer, not the app
    assert out["agent_route"] == 404
    assert out["nl"] == 503                           # natural language says it is unavailable; it does not crash
    assert out["leaked"] == []


def test_ai_layer_can_be_switched_off_explicitly():
    code = f"ROOT = {str(ROOT)!r}\nimport os, sys, json\nsys.path.insert(0, ROOT)\nos.chdir(ROOT)\n" + textwrap.dedent('''
        import api
        from fastapi.testclient import TestClient
        c = TestClient(api.app)
        print(json.dumps({"active": api.AI_LAYER_ACTIVE, "agent": c.get("/agent/health").status_code,
                          "enterprise": c.get("/enterprise/health").status_code,
                          "sparql": c.get("/health").status_code}))
    ''')
    import os

    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=240,
                          env={**os.environ, "ENVIRONMENT": "development", "ENABLE_AI_LAYER": "false", "PYTHONUTF8": "1"})
    assert done.returncode == 0, done.stderr[-800:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out == {"active": False, "agent": 404, "enterprise": 404, "sparql": 200}


def test_validation_and_generation_run_without_llm_or_neo4j():
    out = run_blocked('''
        import json
        from core.shacl_validator import ShaclValidator
        from services import sample_data
        from services.graph_projection import build_projection
        from rdflib import Graph
        from core.dataset import Dataset
        result = ShaclValidator().validate_ontology()
        g = Dataset.default().graph()
        problems = sample_data.check_dataset(sample_data.load_dataset(), sample_data.load_drug_reference(),
                                             source_dir=sample_data.SOURCE_DIR)
        print(json.dumps({"conforms": result.summary.conforms, "nodes": len(build_projection(g).nodes),
                          "problems": len(problems),
                          "leaked": sorted(m for m in sys.modules if m.split(".")[0] in BLOCK | {"agents"})}))
    ''')
    assert out["conforms"] is True and out["nodes"] == 124 and out["problems"] == 0 and out["leaked"] == []


def test_abstention_and_provenance_need_no_llm():
    """The refuse-instead-of-fabricate rule is plain Python over evidence, so it is testable offline."""
    out = run_blocked('''
        import json
        from enterprise.abstention import decide_abstention
        grounded = {"query_type": "sparql", "validated_query": "SELECT ?p WHERE { ?p a hc:Patient }",
                    "results": [{"p": "PatientJohn"}] * 6, "validation_ok": True,
                    "retrieved_concepts": [{"name": "Patient", "rerank_score": 0.9}]}
        ungrounded = {"query_type": "sparql", "validated_query": "SELECT ?p WHERE { ?p a hc:Patient }", "results": [],
                      "validation_ok": True}
        rejected = dict(grounded, human_decision="rejected")
        print(json.dumps({k: decide_abstention(v)["refusal_reason"] for k, v in
                          {"grounded": grounded, "ungrounded": ungrounded, "rejected": rejected}.items()}))
    ''')
    assert out == {"grounded": None, "ungrounded": "missing_provenance", "rejected": "human_rejected"}


# ---- packaging --------------------------------------------------------------------------------------------

def _requirements(name: str) -> list[str]:
    return [l.strip() for l in (ROOT / name).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def test_core_requirements_are_a_subset_of_the_full_requirements():
    assert set(_requirements("requirements-core.txt")) <= set(_requirements("requirements.txt"))


def test_core_requirements_name_no_ai_package():
    names = {l.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip().lower().replace("-", "_") for l in _requirements("requirements-core.txt")}
    assert not names & {"openai", "langchain", "langchain_openai", "langchain_core", "langgraph", "langsmith",
                        "opentelemetry_api", "opentelemetry_sdk", "streamlit"}


def test_every_ai_package_in_requirements_is_outside_the_core_list():
    core = set(_requirements("requirements-core.txt"))
    ai = [l for l in _requirements("requirements.txt") if l not in core]
    assert {l.split("=")[0].split(">")[0].lower() for l in ai} >= {"openai", "langgraph", "streamlit"}
