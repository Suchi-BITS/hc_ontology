"""The CI hygiene checks are tested like any other code: each must FAIL on a bad input and PASS on the repository.

A check that has never been seen failing is a check nobody knows works. Fake keys are built at run time from parts so
that this file itself contains nothing key-shaped for the secret scan to find.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ci_checks as cc  # noqa: E402


def key(prefix: str, n: int = 32) -> str:
    return prefix + "A1b2C3d4" * (n // 8)


# ---- the repository itself passes ---------------------------------------------------------------------------------------

def test_the_repository_passes_every_hygiene_check():
    found = cc.run()
    assert found == [], "\n".join(str(f) for f in found)


# ---- 1. forbidden files --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", [".env", "config/.env", ".env.production", ".credentials.json", "certs/server.pem", "id.key",
                                  "venv/bin/python", ".venv/lib/x.py", "services/__pycache__/a.pyc", "x.pyc", ".pytest_cache/v",
                                  "secrets/db.txt", ".streamlit/secrets.toml"])
def test_files_that_must_never_be_committed_are_found(path):
    assert [f.path for f in cc.check_files(ROOT, [path])] == [path]


@pytest.mark.parametrize("path", [".env.example", "services/load_ontology.py", "docs/security-policy.md", "environment.md", "docs/venv-notes.md"])
def test_ordinary_files_are_not_flagged(path):
    assert cc.check_files(ROOT, [path]) == []


# ---- 2. secrets -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,what", [
    (f"OPENAI_API_KEY={key('sk-')}", "OpenAI"),
    (f"key = '{key('sk-proj-')}'", "OpenAI"),
    (f"LANGCHAIN_API_KEY={key('lsv2_pt_')}", "LangSmith"),
    (f"X-API-Key: {key('hck_')}", "project"),
    ("aws " + "AKIA" + "ABCDEFGHIJKLMNOP", "AWS"),
    ("token " + "ghp_" + "a" * 36, "GitHub"),
    ("-----BEGIN " + "RSA PRIVATE KEY-----", "private key"),
    ("NEO4J_PASSWORD=hunter2-real-looking", "NEO4J_PASSWORD"),
    ('NEO4J_PASSWORD: "S3cretPassw0rd"', "NEO4J_PASSWORD"),
])
def test_secrets_are_found(text, what):
    found = cc.secret_findings("config.yaml", text)
    assert len(found) == 1 and what.lower() in found[0].message.lower()


@pytest.mark.parametrize("text", [
    "NEO4J_PASSWORD=<your-neo4j-password>", "NEO4J_PASSWORD=", "NEO4J_PASSWORD: ci-only-password-1", "NEO4J_PASSWORD=${NEO4J_PASSWORD}",
    'NEO4J_PASSWORD: "${NEO4J_PASSWORD:?Set it}"', "kubectl ... --from-literal=NEO4J_PASSWORD=...",
    "OPENAI_API_KEY=sk-test-placeholder-no-network-calls-are-made", "@apiKey = hck_replace_with_your_key",
    "the sk-learn library", "task-queue", f"{key('hck_')}  # pragma: allowlist secret",
])
def test_placeholders_prose_and_marked_fixtures_are_not_secrets(text):
    assert cc.secret_findings("docs/x.md", text) == []


def test_python_files_building_env_lines_are_not_password_findings():
    assert cc.secret_findings("scripts/dev.py", 'text = f"NEO4J_PASSWORD={password}"') == []
    assert len(cc.secret_findings("scripts/dev.py", f"k = '{key('sk-')}'")) == 1       # but a real-looking key still is


# ---- 3. image tags ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel,text,count", [
    ("Dockerfile", "FROM python:latest AS runtime", 1),
    ("Dockerfile", "FROM python AS runtime", 1),
    ("k8s/deployment.yaml", "          image: ghcr.io/o/app:latest", 1),
    ("k8s/deployment.yaml", "          image: ghcr.io/o/app", 1),
    ("docker_compose.yaml", "    image: neo4j", 1),
    (".github/workflows/cd.yml", "            type=raw,value=latest,enable=true", 1),
    ("Dockerfile", "FROM python:3.11-slim AS builder", 0),
    ("Dockerfile", "FROM python:3.11-slim AS builder" + chr(10) + "FROM builder AS runtime", 0),   # a later stage built on an earlier one
    ("docker_compose.yaml", "    image: neo4j:5.26-community", 0),
    ("k8s/deployment.yaml", "          image: ghcr.io/o/app:1.0.0", 0),
    ("k8s/deployment.yaml", "          image: ghcr.io/o/app@sha256:" + "0" * 64, 0),
    ("Dockerfile", "# FROM python:latest  (a comment)", 0),
])
def test_unpinned_images_are_found(rel, text, count):
    assert len(cc.image_findings(rel, text)) == count


# ---- 4. Docker configuration -----------------------------------------------------------------------------------------------------------

GOOD = "FROM python:3.11-slim\nRUN useradd app\nUSER app\nHEALTHCHECK CMD true\nRUN pip install -r requirements.txt -c constraints.txt\n"


def test_a_good_dockerfile_passes():
    assert cc.dockerfile_findings("Dockerfile", GOOD) == []


@pytest.mark.parametrize("text,fragment", [
    (GOOD.replace("USER app\n", ""), "non-root"),
    (GOOD.replace("USER app", "USER root"), "non-root"),
    (GOOD.replace("HEALTHCHECK CMD true\n", ""), "HEALTHCHECK"),
    (GOOD + "ADD https://example.org/x.tgz /x\n", "ADD from a URL"),
    (GOOD + "COPY .env /app/.env\n", ".env"),
    (GOOD.replace(" -c constraints.txt", ""), "constraints"),
])
def test_a_bad_dockerfile_is_found(text, fragment):
    found = cc.dockerfile_findings("Dockerfile", text)
    assert any(fragment in f.message for f in found), found


@pytest.mark.parametrize("text,fragment", [
    ("    privileged: true", "privileged"),
    ("    network_mode: host", "host networking"),
    ("      - /var/run/docker.sock:/var/run/docker.sock", "Docker socket"),
    ("    cap_add:", "capabilities"),
    ('      - "8000:8000"', "every interface"),
    ("      ENVIRONMENT: ${ENVIRONMENT:-development}", "production-mode"),
])
def test_unsafe_compose_settings_are_found(text, fragment):
    assert any(fragment in f.message for f in cc.compose_findings("docker_compose.yaml", text))


def test_loopback_and_variable_bound_ports_are_fine():
    ok = '      - "127.0.0.1:8000:8000"\n      - "${API_BIND:-127.0.0.1}:${API_PORT:-8000}:8000"\n'
    assert cc.compose_findings("docker_compose.yaml", ok) == []


def test_dockerignore_must_exclude_secrets_and_history():
    assert len(cc.dockerignore_findings("venv\n")) == 3
    assert cc.dockerignore_findings(".env\n.git\nvenv\n.credentials.json\n") == []


# ---- 5. workflows -----------------------------------------------------------------------------------------------------------------------

def test_workflow_rules():
    ok = "name: x\non:\n  push:\npermissions:\n  contents: read\njobs: {}\n"
    assert cc.workflow_findings(".github/workflows/ci.yml", ok) == []
    assert any("permissions" in f.message for f in cc.workflow_findings(".github/workflows/ci.yml", "name: x\non:\n  push:\n"))
    assert any("pull_request_target" in f.message for f in cc.workflow_findings(".github/workflows/ci.yml", ok + "  pull_request_target:\n"))
    assert any("OpenAI" in f.message for f in cc.workflow_findings(".github/workflows/ci.yml", ok + "      key: ${{ secrets.OPENAI_API_KEY }}\n"))
    assert any("AI credential" in f.message for f in cc.workflow_findings(".github/workflows/ci.yml", ok + "      OPENAI_API_KEY: sk-x\n"))


def test_the_live_ai_workflow_may_use_the_secret_but_only_manually():
    manual = "name: l\non:\n  workflow_dispatch:\npermissions:\n  contents: read\n      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}\n"
    assert cc.workflow_findings(".github/workflows/live-ai.yml", manual) == []
    automatic = manual.replace("on:\n  workflow_dispatch:", "on:\n  push:\n  workflow_dispatch:")
    assert any("manual" in f.message for f in cc.workflow_findings(".github/workflows/live-ai.yml", automatic))


# ---- 6. weak assertions ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("source,count", [
    ("def test_a():\n    assert x or True\n", 1), ("def test_a():\n    assert True\n", 1), ("def test_a():\n    assert len(r) > 0\n", 1),
    ("def test_a():\n    assert n >= 0\n", 1), ("def test_a():\n    assert v is not None\n", 1),
    ("def test_a():\n    assert len(r) == 5\n", 0), ("def test_a():\n    assert v == 'x'\n", 0), ("def test_a():\n    assert a or b\n", 0),
])
def test_weak_assertions_are_found(source, count):
    assert len(cc.assertion_findings("tests/test_x.py", source)) == count


# ---- 7. documentation --------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "whole suite, ~500 tests, no Neo4j", "480 passed, 7 expected failures", "1,226 tests pass", "about 100 tests", "~530 tests",
    "this has 3 expected failures",
])
def test_stale_suite_size_claims_are_found(line):
    assert len(cc.doc_findings("docs/x.md", line)) == 1


@pytest.mark.parametrize("line", [
    "pytest --collect-only -q counts the suite", "the suite has 30 tests in this file", "list skips and expected failures with reasons",
    "this test runs 5 patients",
])
def test_ordinary_test_prose_is_not_a_suite_claim(line):
    assert cc.doc_findings("docs/x.md", line) == []


@pytest.mark.parametrize("line", [
    "the file healthcare_ontology.owl holds everything", "set OWL_FILE_PATH=x", "export AUTH_MODE=development-open",
    "POST /neo4j/seed-demo wipes the database", "validator.execute_with_timeout(fn, q)",
])
def test_retired_names_are_found_in_current_docs(line):
    assert len(cc.doc_findings("docs/x.md", line)) == 1


def test_retired_names_may_appear_when_the_line_tells_the_history():
    assert cc.doc_findings("docs/x.md", "OWL_FILE_PATH was replaced by ONTOLOGY_SCHEMA_FILE") == []
    assert cc.doc_findings("docs/x.md", "POST /neo4j/seed-demo was removed") == []


def test_dated_records_and_task_files_are_not_current_documentation():
    files = ["readme.md", "docs/a.md", "docs/fresh-clone-verification.md", "docs/AI_LAYER_LIVE_VERIFICATION.md", "docs/UDEMY_X.md",
             "P12.md", "FINAL_INDEPENDENT_AUDIT.md", "agents/P2.md", "src/x.py", "system_design.md"]
    assert cc.current_docs(files) == ["readme.md", "docs/a.md", "system_design.md"]


def test_wrong_counts_and_dead_references_are_found(tmp_path):
    (tmp_path / "sparql").mkdir()
    for i in range(3):
        (tmp_path / "sparql" / f"cq{i}.rq").write_text("x", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "a.md").write_text("There are 21 competency questions. See [real](real.md), [gone](gone.md) and `sparql/missing.rq`, `sparql/cq0.rq`.", encoding="utf-8")
    found = cc.check_docs(tmp_path, ["docs/a.md"])
    messages = " | ".join(f.message for f in found)
    assert "claims 21 competency questions" in messages and "there are 3" in messages
    assert "gone.md" in messages and "sparql/missing.rq" in messages
    assert "real.md" not in messages and "cq0.rq" not in messages


# ---- the workflows themselves -----------------------------------------------------------------------------------------------------------------------

def workflow(name):
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_ci_has_the_jobs_the_requirements_name():
    text = workflow("ci.yml")
    for job in ("hygiene:", "test:", "neo4j:", "docker:"):
        assert re.search(rf"(?m)^  {job}", text), job
    for stage in ("ci.py hygiene", "ci.py validate", "ci.py tests", "ci.py neo4j", "ci.py docker"):
        assert stage in text, stage
    assert "setup-java" in text, "the OWL reasoner must run in CI"
    assert re.search(r"image: neo4j:\d+\.\d+", text), "the Neo4j job uses a real, pinned server"


def test_every_script_a_workflow_runs_exists():
    for name in ("ci.yml", "cd.yml", "live-ai.yml"):
        for script in re.findall(r"scripts/[\w./]+\.py", workflow(name)):
            assert (ROOT / script).is_file(), f"{name} runs {script}"


def test_every_ci_stage_the_workflow_calls_is_a_defined_stage():
    import ci

    called = set(re.findall(r"ci\.py (\w+)", re.sub(r"(?m)^\s*#.*$", "", workflow("ci.yml"))))
    assert called and called <= set(ci.STAGES), called - set(ci.STAGES)


def test_the_normal_build_has_no_ai_credential_and_the_live_one_is_manual():
    assert not re.search(r"OPENAI|LANGCHAIN|LANGSMITH", re.sub(r"(?m)^\s*#.*$", "", workflow("ci.yml")), re.I) or \
        "secrets." not in workflow("ci.yml")
    live = workflow("live-ai.yml")
    assert "workflow_dispatch" in live and not re.search(r"(?m)^\s+(push|pull_request):", live)
    assert 'LANGCHAIN_TRACING_V2: "false"' in live and "secrets.OPENAI_API_KEY" in live


def test_the_test_stage_cannot_reach_openai_or_a_live_neo4j():
    text = (ROOT / "scripts" / "ci.py").read_text(encoding="utf-8")
    block = text[text.index("def stage_tests"):text.index("def dotenv_neo4j")]
    for variable in ("OPENAI_API_KEY", "RUN_LIVE_AI", "RUN_LIVE_NEO4J", "LANGCHAIN_API_KEY"):
        assert variable in block
    assert 'LANGCHAIN_TRACING_V2": "false"' in block and "opt-in" in block


def test_the_docker_stage_checks_what_the_requirements_name():
    text = (ROOT / "scripts" / "ci.py").read_text(encoding="utf-8")
    block = text[text.index("def stage_docker"):text.index("STAGES = ")]
    for needle in ("docker\", \"build", "id\", IMAGE, \"-u", "requires authentication", "Health.Status", "401", "Traceback", "docker_compose.dev.yaml"):
        assert needle in block, needle
    assert "ci-only" in block and "sk-" not in block


def test_a_stage_that_cannot_run_reports_not_run_never_pass(monkeypatch):
    import ci

    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    assert ci.stage_docker() == 2
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.setattr(ci, "dotenv_neo4j", lambda: None)
    assert ci.stage_neo4j() == 2
