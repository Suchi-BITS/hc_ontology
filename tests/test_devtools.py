"""The reproducibility tooling itself: bootstrap script, pinned dependencies, container files."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def dev():
    spec = importlib.util.spec_from_file_location("dev_script", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- .env creation -------------------------------------------------------------------------

def test_env_file_is_created_with_a_generated_password_and_no_openai_key(dev, tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    dev.ensure_env_file()
    env = dev.read_env_file()
    assert len(env["NEO4J_PASSWORD"]) >= 16 and not dev.is_placeholder(env["NEO4J_PASSWORD"])
    assert env["OPENAI_API_KEY"] == ""
    assert env["NEO4J_DATABASE"] == "neo4j"


def test_each_generated_password_is_different(dev, tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("NEO4J_PASSWORD=<x>\nOPENAI_API_KEY=<y>\n", encoding="utf-8")
    dev.ensure_env_file()
    first = dev.read_env_file()["NEO4J_PASSWORD"]
    (tmp_path / ".env").unlink()
    dev.ensure_env_file()
    assert dev.read_env_file()["NEO4J_PASSWORD"] != first


def test_an_existing_env_file_is_never_overwritten(dev, tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("NEO4J_PASSWORD=<x>\n", encoding="utf-8")
    (tmp_path / ".env").write_text("NEO4J_PASSWORD=mine\n", encoding="utf-8")
    dev.ensure_env_file()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "NEO4J_PASSWORD=mine\n"


@pytest.mark.parametrize("value,expected", [("", True), (None, True), ("<your-key>", True), ("real", False), ("a<b>", False)])
def test_placeholder_detection(dev, value, expected):
    assert dev.is_placeholder(value) is expected


# ---- pip TLS fallback ---------------------------------------------------------------------------

class FakePopen:
    """Replays scripted pip outcomes: (exit code, output)."""

    scripted: list = []
    calls: list = []

    def __init__(self, cmd, **kwargs):
        FakePopen.calls.append(list(cmd))
        self._code, text = FakePopen.scripted.pop(0)
        self.stdout = iter(text.splitlines(keepends=True))

    def wait(self):
        return self._code


SSL = "WARNING ... SSLCertVerificationError CERTIFICATE_VERIFY_FAILED ...\n"


def run_pip(dev, monkeypatch, script, fix_code=0):
    FakePopen.scripted, FakePopen.calls = list(script), []
    monkeypatch.setattr(dev.subprocess, "Popen", FakePopen)
    ran = []
    monkeypatch.setattr(
        dev.subprocess, "run",
        lambda cmd, **kw: ran.append(list(cmd)) or subprocess.CompletedProcess(cmd, fix_code),
    )
    dev.pip_install(["-r", "requirements.txt"])
    return FakePopen.calls, ran


def test_pip_succeeds_normally_without_touching_trust_settings(dev, monkeypatch):
    calls, ran = run_pip(dev, monkeypatch, [(0, "ok\n")])
    assert len(calls) == 1 and ran == []
    assert "--trusted-host" not in calls[0]


def test_pip_tls_failure_installs_system_certs_then_retries_with_verification_on(dev, monkeypatch):
    calls, ran = run_pip(dev, monkeypatch, [(1, SSL), (0, "ok\n")])
    assert len(calls) == 2 and "--trusted-host" not in calls[1]  # the retry verifies certificates
    assert "pip-system-certs" in ran[0] and ran[0].count("--trusted-host") == 2  # the one trusted step


def test_pip_tls_failure_last_resort_trusts_only_the_pypi_hosts(dev, monkeypatch):
    calls, _ = run_pip(dev, monkeypatch, [(1, SSL), (1, SSL), (0, "ok\n")])
    hosts = [calls[2][i + 1] for i, c in enumerate(calls[2]) if c == "--trusted-host"]
    assert hosts == ["pypi.org", "files.pythonhosted.org"]


def test_pip_failure_for_another_reason_does_not_weaken_tls(dev, monkeypatch):
    FakePopen.scripted, FakePopen.calls = [(1, "ERROR: No matching distribution found\n")], []
    monkeypatch.setattr(dev.subprocess, "Popen", FakePopen)
    with pytest.raises(SystemExit):
        dev.pip_install(["-r", "requirements.txt"])
    assert len(FakePopen.calls) == 1 and "--trusted-host" not in FakePopen.calls[0]


# ---- dependency pinning --------------------------------------------------------------------------

def parse_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def test_every_requirement_is_covered_by_a_pinned_version_that_satisfies_it():
    from packaging.requirements import Requirement

    constraints = parse_pins(ROOT / "constraints.txt")
    checked = 0
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        name = req.name.lower().replace("_", "-")
        assert name in constraints, f"{req.name} is not pinned in constraints.txt"
        assert req.specifier.contains(constraints[name]), f"{req.name}=={constraints[name]} violates {req.specifier}"
        checked += 1
    assert checked >= 20


def test_requirements_are_split_between_runtime_and_development():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev_text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pytest" not in runtime and "-r requirements.txt" in dev_text and "pytest" in dev_text


def test_constraints_pin_the_semantic_stack_exactly():
    pins = parse_pins(ROOT / "constraints.txt")
    for package in ("rdflib", "pyshacl", "owlready2", "neo4j", "fastapi", "pytest"):
        assert package in pins, package


# ---- container and compose files ----------------------------------------------------------------------

def test_compose_runs_neo4j_before_the_api_and_has_no_ollama_or_source_mount():
    import yaml

    compose = yaml.safe_load((ROOT / "docker_compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"neo4j", "api", "streamlit"}
    assert "healthcheck" in services["neo4j"] and "profiles" not in services["neo4j"]
    assert services["api"]["depends_on"]["neo4j"]["condition"] == "service_healthy"
    assert "volumes" not in services["api"], "a source bind-mount would expose .env inside the container"
    assert services["api"]["environment"]["NEO4J_URI"] == "bolt://neo4j:7687"
    assert not any("ollama" in str(v).lower() for v in services.values())


def test_compose_requires_a_neo4j_password_and_does_not_require_openai():
    text = (ROOT / "docker_compose.yaml").read_text(encoding="utf-8")
    assert "${NEO4J_PASSWORD:?" in text
    assert "${OPENAI_API_KEY:?" not in text and "OPENAI_API_KEY: ${OPENAI_API_KEY:-}" in text
    assert not re.search(r"NEO4J_PASSWORD:-\w", text), "no fallback password"


def test_dockerfile_installs_pinned_versions_and_drops_root():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "-c constraints.txt" in text and "COPY requirements.txt constraints.txt" in text
    assert re.search(r"^USER app$", text, re.M) and "HEALTHCHECK" in text


def test_dockerignore_keeps_secrets_and_local_state_out_of_the_image():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".git", "venv", "__pycache__"):
        assert entry in ignored
    assert "constraints.txt" not in ignored and "requirements.txt" not in ignored


def test_env_example_contains_placeholders_not_secrets():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^NEO4J_PASSWORD=<[^>]+>$", text, re.M) and re.search(r"^OPENAI_API_KEY=<[^>]+>$", text, re.M)
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)
    assert "NEO4J_DATABASE=neo4j" in text


# ---- the documented commands exist ------------------------------------------------------------------------

def test_every_documented_dev_command_exists():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "dev.py"), "--help"], capture_output=True, text=True).stdout
    documented = re.findall(r"python scripts/dev\.py (\w+)", (ROOT / "readme.md").read_text(encoding="utf-8"))
    assert {"setup", "doctor", "validate", "test"} <= set(documented), "the README no longer documents the core commands"
    for command in set(documented):
        assert re.search(rf"\b{command}\b", out), f"README documents `dev.py {command}` but it does not exist"


def test_makefile_targets_match_the_dev_commands():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for command in ("quickstart", "setup", "doctor", "validate", "test", "demo", "up", "load", "down", "serve", "lock"):
        assert command in makefile


# ---- credential management ------------------------------------------------------------------------------

def test_dev_credential_roles_match_the_authorization_table(dev):
    from core.authz import ROLE_PERMISSIONS

    assert set(dev.KNOWN_ROLES) == set(ROLE_PERMISSIONS)


def test_credential_add_stores_only_a_hash_that_the_server_accepts(dev, tmp_path, monkeypatch, capsys):
    import argparse

    from core.security import hash_key

    monkeypatch.setattr(dev, "CREDENTIALS_FILE", tmp_path / ".credentials.json")
    args = argparse.Namespace(action="add", user="suchismita", tenant="abhigya-ai-lab", role="admin", display_name="Suchismita")
    assert dev.cmd_credential(args) == 0
    shown = capsys.readouterr().out
    key = re.search(r"(hck_[A-Za-z0-9_\-]+)", shown).group(1)
    stored = (tmp_path / ".credentials.json").read_text(encoding="utf-8")
    assert key not in stored and hash_key(key) in stored
    record = dev._load_credentials()["credentials"][0]
    assert (record["id"], record["tenant_id"], record["role"]) == ("suchismita", "abhigya-ai-lab", "admin")


def test_credential_add_rejects_unknown_roles_and_duplicates(dev, tmp_path, monkeypatch):
    import argparse

    monkeypatch.setattr(dev, "CREDENTIALS_FILE", tmp_path / ".credentials.json")
    base = dict(action="add", user="u", tenant="t", display_name=None)
    with pytest.raises(SystemExit, match="Unknown role"):
        dev.cmd_credential(argparse.Namespace(role="root", **base))
    assert dev.cmd_credential(argparse.Namespace(role="viewer", **base)) == 0
    with pytest.raises(SystemExit, match="already exists"):
        dev.cmd_credential(argparse.Namespace(role="viewer", **base))


def test_credential_remove_revokes_the_key(dev, tmp_path, monkeypatch):
    import argparse

    monkeypatch.setattr(dev, "CREDENTIALS_FILE", tmp_path / ".credentials.json")
    dev.cmd_credential(argparse.Namespace(action="add", user="u", tenant="t", role="viewer", display_name=None))
    assert dev.cmd_credential(argparse.Namespace(action="remove", user="u", tenant=None, role=None, display_name=None)) == 0
    assert dev._load_credentials()["credentials"] == []


def test_credential_files_are_never_committed_or_shipped_in_the_image():
    assert ".credentials.json" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".credentials.json" in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
