"""README, scripts, Docker configuration and source code must agree. These tests make them.

Each test is a static cross-check that failed at least once on the original repository:
a README that described Ollama while the code used OpenAI, a missing .env.example, three different
Neo4j database names, unpinned dependencies, a compose file that did not parse, and so on.
"""

from __future__ import annotations

import ast
import importlib.metadata as metadata
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_DIRS = ("core", "services", "routers", "agents", "enterprise")
APP_FILES = ("api.py", "streamlit_app.py")


def app_sources():
    for folder in APP_DIRS:
        yield from (ROOT / folder).rglob("*.py")
    for name in APP_FILES:
        yield ROOT / name


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---- README <-> API ------------------------------------------------------------------------------

def test_every_endpoint_in_the_readme_exists_in_the_api(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)  # noqa: E731
    rows = re.findall(r"^\| (?:GET|POST|PUT|DELETE)(?:, (?:GET|POST))? \| `([^`]+)`", read("readme.md"), re.M)
    assert len(rows) >= 40
    missing = [
        p for p in rows
        if "…" not in p and "," not in p and norm(p.split("?")[0]) not in {norm(x) for x in paths}
    ]
    assert missing == [], f"README documents endpoints the API does not have: {missing}"


def test_every_repository_path_the_readme_mentions_exists():
    text = read("readme.md") + read("docs/reproducibility.md")
    candidates = set(re.findall(r"`((?:scripts|docs|sparql|shapes|data|tests)/[A-Za-z0-9_./\-]+\.[A-Za-z0-9]+)`", text))
    candidates |= set(re.findall(r"\]\(((?:docs|scripts)/[A-Za-z0-9_./\-]+\.[a-z]+)\)", text))
    assert len(candidates) >= 8
    missing = sorted(p for p in candidates if not (ROOT / p).exists())
    assert missing == [], f"documented paths that do not exist: {missing}"


# ---- configuration ----------------------------------------------------------------------------------

def test_every_environment_variable_the_code_reads_is_documented_in_env_example():
    pattern = re.compile(r"os\.getenv\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']")
    used = set()
    for path in app_sources():
        used |= set(pattern.findall(path.read_text(encoding="utf-8-sig")))
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", read(".env.example"), re.M))
    assert len(used) >= 50
    assert sorted(used - documented) == [], "variables the code reads but .env.example never mentions"


def test_only_openai_is_configured_as_the_llm_provider():
    for rel in (".env.example", "docker_compose.yaml", "Dockerfile", "readme.md", "core/config.py", "scripts/dev.py"):
        for line in read(rel).splitlines():
            lowered = line.lower()
            if any(word in lowered for word in ("ollama", "nomic", "qwen")):
                assert "not used" in lowered or "no longer" in lowered, f"{rel}: {line.strip()}"


def test_one_neo4j_database_name_everywhere():
    assert re.search(r"^NEO4J_DATABASE=neo4j$", read(".env.example"), re.M)
    assert "NEO4J_DATABASE: neo4j" in read("docker_compose.yaml")
    assert 'NEO4J_DATABASE: "neo4j"' in read("k8s/deployment.yaml")
    assert '"neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j")' in read("core/config.py")
    for rel in ("services/embedding_service.py", "services/neo4j_exporter.py", "services/sparql_to_cypher.py"):
        assert not re.search(r"NEO4J_DATABASE\"\s*,\s*\"(?!neo4j\")", read(rel)), rel
    for rel in ("readme.md", "COURSE_SETUP.md"):
        assert "hcontology" not in read(rel), rel


def test_the_api_port_is_the_same_in_every_place_it_is_stated():
    assert '"${API_BIND:-127.0.0.1}:${API_PORT:-8000}:8000"' in read("docker_compose.yaml")
    assert "EXPOSE 8000" in read("Dockerfile") and "--port\", \"8000\"" in read("Dockerfile")
    assert "--port\", \"8000\"" in read("scripts/dev.py") or '"8000"' in read("scripts/dev.py")
    assert "http://127.0.0.1:8000" in read("core/config.py")


# ---- Python version and dependencies --------------------------------------------------------------------

def test_every_place_that_names_a_python_version_agrees():
    wanted = read(".python-version").strip()
    assert wanted == "3.11"
    assert f"python:{wanted}-slim" in read("Dockerfile")
    assert f'python-version: "{wanted}"' in read(".github/workflows/ci.yml")
    assert 'requires-python = ">=3.11"' in read("pyproject.toml")
    assert re.search(r"MIN_PYTHON = \(3, 11\)", read("scripts/dev.py"))
    assert sys.version_info >= (3, 11)


def test_pyproject_is_valid_and_matches_the_requirement_files():
    data = tomllib.loads(read("pyproject.toml"))
    assert data["project"]["dynamic"] == ["dependencies"]
    assert data["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == ["requirements.txt"]
    dev_pins = {l.strip() for l in read("requirements-dev.txt").splitlines() if l.strip() and not l.startswith(("#", "-r"))}
    assert set(data["project"]["optional-dependencies"]["dev"]) == dev_pins
    assert data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_pytest_is_configured_in_exactly_one_place():
    assert not (ROOT / "pytest.ini").exists() and not (ROOT / "tox.ini").exists() and not (ROOT / "setup.cfg").exists()


def test_every_third_party_import_in_the_application_is_pinned():
    pinned = {
        l.split("==")[0].lower().replace("_", "-")
        for l in read("constraints.txt").splitlines()
        if l and not l.startswith("#")
    }
    distributions = metadata.packages_distributions()
    local = {p.stem for p in ROOT.glob("*.py")} | {p.name for p in ROOT.iterdir() if p.is_dir()}
    unpinned = {}
    for path in app_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in sys.stdlib_module_names or name in local:
                    continue
                dist = (distributions.get(name) or [None])[0]
                if not dist or dist.lower().replace("_", "-") not in pinned:
                    unpinned.setdefault(name, path.name)
    assert unpinned == {}, f"imported but not in constraints.txt: {unpinned}"


def test_constraints_do_not_carry_unrelated_packages():
    pinned = {l.split("==")[0].lower() for l in read("constraints.txt").splitlines() if l and not l.startswith("#")}
    for leftover in ("ollama", "langchain-ollama", "langchain-community", "sqlalchemy", "aiohttp"):
        assert leftover not in pinned, f"{leftover} is a leftover from a developer's virtualenv"


# ---- Docker --------------------------------------------------------------------------------------------------

def test_files_copied_or_run_by_docker_exist():
    dockerfile = read("Dockerfile")
    for rel in re.findall(r"^COPY (?!--from)(\S+)(?: \S+)* (?:\S+)$", dockerfile, re.M):
        for part in rel.split():
            if part not in (".", "./"):
                assert (ROOT / part).exists(), f"Dockerfile copies missing {part}"
    compose = read("docker_compose.yaml")
    for script in re.findall(r"python (scripts/[\w./]+\.py)", compose):
        assert (ROOT / script).exists(), script
    assert (ROOT / "validation_reports").is_dir(), "the report directory must exist in a fresh clone"


def test_the_image_receives_no_secrets_and_no_local_state():
    ignore = read(".dockerignore").splitlines()
    assert {".env", ".git", "venv", "__pycache__"} <= set(ignore)
    dockerfile = read("Dockerfile")
    assert not re.search(r"^(ENV|ARG)\s+\w*(KEY|PASSWORD|SECRET|TOKEN)\w*\s*=?\s*\S+", dockerfile, re.M | re.I)


def test_gitignore_excludes_the_files_that_must_never_be_committed():
    ignored = read(".gitignore").splitlines()
    assert {".env", ".env.*", "!.env.example", "venv/", "__pycache__/"} <= set(ignored)


def test_required_directories_exist_in_a_fresh_clone():
    for rel in ("validation_reports/.gitkeep", "shapes", "data/sample_instances", "sparql", "docs"):
        assert (ROOT / rel).exists(), f"{rel} is missing from the repository"


# ---- the documented flow ---------------------------------------------------------------------------------------

def test_fresh_clone_checklist_exists_and_separates_what_is_verified():
    text = read("docs/fresh-clone-verification.md")
    for label in ("VERIFIED", "STATICALLY VERIFIED", "NOT VERIFIED"):
        assert label in text
    assert "python scripts/dev.py quickstart" in text


@pytest.mark.parametrize("script", ["validate.py", "load_graph.py", "demo.py", "dev.py", "generate_hc_ontology.py"])
def test_every_script_has_a_usage_docstring_and_compiles(script):
    source = read(f"scripts/{script}")
    tree = ast.parse(source)
    assert ast.get_docstring(tree), f"{script} needs a docstring that explains how to run it"
    compile(source, script, "exec")


# ---- the README's examples are executable -------------------------------------------------------------------------

def _readme_json_examples():
    """The JSON bodies of the curl examples in the 'Query examples' section."""
    import json

    section = read("readme.md").split("### 11. Query examples", 1)[1].split("After step 7", 1)[0]
    bodies = re.findall(r"-d '(\{.*?\})'", section, re.S)
    return [json.loads(b) for b in bodies]


def test_the_readme_sparql_example_returns_the_answer_the_readme_states(client):
    sparql = next(b for b in _readme_json_examples() if "query" in b)
    response = client.post("/sparql", json=sparql)
    assert response.status_code == 200, response.text
    assert sorted(r[0].split("#")[-1] for r in response.json()["results"]) == ["PatientAlice", "PatientBob"]


def test_the_readme_validation_example_reports_the_violations_the_readme_states(client):
    body = next(b for b in _readme_json_examples() if "data" in b)
    response = client.post("/validate", json=body)
    assert response.status_code == 200
    messages = {v["message"] for v in response.json()["violations"] if v["severity"] == "Violation"}
    for field in ("firstName", "lastName", "dateOfBirth"):
        assert f"Patient must have a {field}." in messages


def test_plain_and_typed_string_literals_both_match_in_sparql_queries(client):
    base = ("PREFIX hc: <http://example.org/healthcare-hospital.owl#> SELECT ?c WHERE "
            "{ ?c hc:codeValue %s }")
    plain = client.post("/sparql", json={"query": base % '"E11"'}).json()["results"]
    filtered = client.post("/sparql", json={"query": base.replace("%s", "?v . FILTER(?v = \"E11\")")}).json()["results"]
    assert plain and plain == filtered
