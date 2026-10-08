"""The CI stages, runnable locally exactly as GitHub runs them. Standard library only.

    python scripts/ci.py hygiene          # secrets, tracked .env/venv, :latest tags, Docker config, weak assertions, stale docs
    python scripts/ci.py validate         # contract, schema, SHACL, projection plan, OWL reasoner, offline demo
    python scripts/ci.py tests            # the whole suite; any skip other than an opt-in live test is a failure
    python scripts/ci.py neo4j            # needs Neo4j (NEO4J_* variables): load twice, compare with the RDF, live tests
    python scripts/ci.py docker           # needs Docker: build, run as non-root, health, auth, no secrets in the image
    python scripts/ci.py all              # hygiene, validate, tests (+ neo4j / docker with --neo4j / --docker)

.github/workflows/ci.yml calls these same stages, so "it passes locally" and "it passes in CI" mean the same thing.
No stage needs a real secret: a Neo4j password for the throwaway service container, and a made-up API key for the image.
No stage may call OpenAI: the normal build uses the fakes in the test suite; real calls live in the manual live-ai workflow.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "healthcare-ontology-api:ci"


def python() -> str:
    """The project's virtual environment if there is one (CI creates it with dev.py setup), else this interpreter."""
    for candidate in (ROOT / "venv" / "bin" / "python", ROOT / "venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run(cmd: list[str], *, env: dict | None = None, check: bool = True, capture: bool = False, timeout: int | None = None):
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, env={**os.environ, **(env or {})}, check=check, timeout=timeout,
                          capture_output=capture, text=capture)


def banner(name: str) -> None:
    print(f"\n{'=' * 78}\n  {name}\n{'=' * 78}", flush=True)


# ---- hygiene -------------------------------------------------------------------------------------------------------

def stage_hygiene() -> int:
    banner("hygiene: secrets, tracked files, image tags, Docker config, workflows, weak assertions, stale docs")
    return run([sys.executable, "scripts/ci_checks.py"], check=False).returncode


# ---- validate -------------------------------------------------------------------------------------------------------

def stage_validate() -> int:
    banner("validate: contract, schema + data, SHACL, projection plan, OWL reasoner, offline demo")
    if shutil.which("java") is None:
        print("Java is required here: the OWL reasoner is part of CI (install a JRE).")
        return 1
    code = run([python(), "scripts/validate.py", "--reasoner"], check=False).returncode
    if code:
        return code
    return run([python(), "scripts/demo.py"], check=False, capture=False).returncode


# ---- tests ----------------------------------------------------------------------------------------------------------

def stage_tests() -> int:
    banner("tests: the whole suite (ontology, reasoner, SHACL, SPARQL, projection, API, security, boundaries, docs)")
    env = {"LANGCHAIN_TRACING_V2": "false", "OTEL_ENABLED": "false"}
    for secret in ("OPENAI_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "RUN_LIVE_AI", "RUN_LIVE_NEO4J"):
        os.environ.pop(secret, None)          # the normal build can neither spend money nor reach a third party
    done = run([python(), "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider"], env=env, check=False, capture=True)
    sys.stdout.write(done.stdout[-6000:] if done.stdout else "")
    sys.stderr.write(done.stderr[-2000:] if done.stderr else "")
    if done.returncode:
        return done.returncode
    # Skips must be exactly the opt-in live tests. A skipped reasoner test would hide a broken ontology.
    skips = re.findall(r"(?m)^SKIPPED \[(\d+)\] \S+: (.*)$", done.stdout)
    unexpected = [(n, why) for n, why in skips if "opt-in" not in why and "RUN_LIVE" not in why]
    if unexpected:
        print("\nUNEXPECTED SKIPS (only opt-in live tests may skip):")
        for n, why in unexpected:
            print(f"  {n} x {why}")
        return 1
    # Reproducibility: a clean checkout stays clean. A test run must not rewrite a tracked file.
    status = run(["git", "status", "--porcelain", "--untracked-files=no"], capture=True, check=False)
    if status.returncode == 0 and status.stdout.strip() and os.environ.get("CI"):
        print("\nTHE TEST RUN MODIFIED TRACKED FILES (a generator output or fixture is not reproducible):")
        print(status.stdout)
        return 1
    print("\ntests: passed; skips were only opt-in live tests; the working tree is unchanged")
    return 0


# ---- neo4j ----------------------------------------------------------------------------------------------------------

def dotenv_neo4j() -> None:
    """Locally the connection is in the git-ignored .env; CI sets real environment variables. Only NEO4J_* is read, never printed."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().startswith("NEO4J_") and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def stage_neo4j() -> int:
    banner("neo4j: load the projection into a real Neo4j twice, compare it with the RDF, run the live tests")
    dotenv_neo4j()
    missing = [v for v in ("NEO4J_URI", "NEO4J_PASSWORD") if not os.environ.get(v)]
    if missing:
        print(f"Set {', '.join(missing)} (and NEO4J_DATABASE) to point at a Neo4j.")
        return 2
    env = {"NEO4J_DATABASE": os.environ.get("NEO4J_DATABASE", "neo4j"), "LANGCHAIN_TRACING_V2": "false"}
    steps = [
        [python(), "scripts/verify_neo4j.py"],
        [python(), "scripts/load_graph.py", "--wait", "90", "--verify"],
        [python(), "scripts/load_graph.py", "--verify"],                               # idempotent
        [python(), "scripts/verify_neo4j.py", "--projection", "--census"],
    ]
    for step in steps:
        if run(step, env=env, check=False).returncode:
            return 1
    live = run([python(), "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider", "tests/test_neo4j_live.py"],
               env={**env, "RUN_LIVE_NEO4J": "1"}, check=False, capture=True)
    sys.stdout.write(live.stdout[-4000:] or "")
    if live.returncode or re.search(r"\b\d+ skipped\b", live.stdout or ""):
        print("the live Neo4j tests must PASS, not skip")
        return 1
    return 0


# ---- docker ---------------------------------------------------------------------------------------------------------

def http(url: str, key: str | None = None) -> int:
    request = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def stage_docker() -> int:
    banner("docker: build, non-root, no secrets in the image, refuses to start unauthenticated, healthy, enforces auth")
    if shutil.which("docker") is None or run(["docker", "info"], check=False, capture=True).returncode != 0:
        print("Docker is not available (no CLI or no daemon): NOT RUN.")
        return 2
    problems: list[str] = []
    run(["docker", "build", "-t", IMAGE, "."])

    uid = run(["docker", "run", "--rm", "--entrypoint", "id", IMAGE, "-u"], capture=True).stdout.strip()
    print(f"container user id: {uid}")
    if uid in ("", "0"):
        problems.append("the image runs as root")

    found = run(["docker", "run", "--rm", "--entrypoint", "sh", IMAGE, "-c",
                 "ls -A /app | grep -E '^(\\.env|\\.git|venv|\\.venv|\\.credentials\\.json|\\.pytest_cache)$' || true"], capture=True).stdout.split()
    print(f"forbidden entries in /app: {found or 'none'}")
    if found:
        problems.append(f"the image contains {found}")

    # Production mode with no credentials must REFUSE TO START (it must not come up open).
    refused = run(["docker", "run", "--rm", "-e", "ENVIRONMENT=production", IMAGE], check=False, capture=True, timeout=120)
    text = (refused.stdout or "") + (refused.stderr or "")
    print(f"no credentials: exit {refused.returncode}")
    if refused.returncode == 0 or "requires authentication" not in text:
        problems.append("the container started without credentials in production mode")

    name = "hc-ci-api"
    run(["docker", "rm", "-f", name], check=False, capture=True)
    run(["docker", "run", "-d", "--name", name, "-p", "127.0.0.1:8000:8000", "-e", "ENVIRONMENT=production",
         "-e", "ALLOW_OPEN_DEVELOPMENT_MODE=false", "-e", "API_KEY=ci-only-made-up-key-0000", "-e", "API_KEY_ROLE=analyst", IMAGE])
    try:
        status = ""
        for _ in range(45):
            status = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name], capture=True, check=False).stdout.strip()
            if status in ("healthy", "unhealthy"):
                break
            time.sleep(2)
        print(f"health status: {status}")
        if status != "healthy":
            problems.append(f"the container did not become healthy ({status or 'no status'})")
        checks = {"GET /health (public)": (http("http://127.0.0.1:8000/health"), 200),
                  "GET /patients without a key": (http("http://127.0.0.1:8000/patients"), 401),
                  "GET /patients with the key": (http("http://127.0.0.1:8000/patients", "ci-only-made-up-key-0000"), 200),
                  "GET /patients with a wrong key": (http("http://127.0.0.1:8000/patients", "wrong"), 401)}
        for label, (got, want) in checks.items():
            print(f"{label}: {got} (want {want})")
            if got != want:
                problems.append(f"{label} returned {got}, wanted {want}")
        who = run(["docker", "exec", name, "id", "-u"], capture=True, check=False).stdout.strip()
        if who in ("", "0"):
            problems.append("the running process is root")
        logs = run(["docker", "logs", name], capture=True, check=False)
        output = (logs.stdout or "") + (logs.stderr or "")
        if "Traceback" in output:
            problems.append("the container log contains a traceback")
        if "ci-only-made-up-key-0000" in output:
            problems.append("the API key appears in the container log")
    finally:
        run(["docker", "rm", "-f", name], check=False, capture=True)

    compose_env = {"NEO4J_PASSWORD": "ci-only-password-1"}
    default = run(["docker", "compose", "-f", "docker_compose.yaml", "config"], env=compose_env, capture=True, check=False)
    if default.returncode or "ENVIRONMENT: production" not in default.stdout or 'ALLOW_OPEN_DEVELOPMENT_MODE: "false"' not in default.stdout:
        problems.append("the default Compose file is not production-mode")
    if re.search(r"host_ip: (0\.0\.0\.0|\"\")", default.stdout or ""):
        problems.append("the default Compose file publishes a port on every interface")
    dev = run(["docker", "compose", "-f", "docker_compose.yaml", "-f", "docker_compose.dev.yaml", "config", "-q"], env=compose_env, check=False, capture=True)
    if dev.returncode:
        problems.append("the development override does not validate")

    for p in problems:
        print(f"PROBLEM: {p}")
    return 1 if problems else 0


STAGES = {"hygiene": stage_hygiene, "validate": stage_validate, "tests": stage_tests, "neo4j": stage_neo4j, "docker": stage_docker}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stages", nargs="+", choices=[*STAGES, "all"])
    parser.add_argument("--neo4j", action="store_true", help="with `all`: also run the Neo4j stage")
    parser.add_argument("--docker", action="store_true", help="with `all`: also run the Docker stage")
    args = parser.parse_args()
    names = []
    for stage in args.stages:
        names += ["hygiene", "validate", "tests", *(["neo4j"] if args.neo4j else []), *(["docker"] if args.docker else [])] if stage == "all" else [stage]
    results = {}
    for name in names:
        started = time.time()
        results[name] = STAGES[name]()
        print(f"\n--> {name}: {'PASS' if results[name] == 0 else ('NOT RUN' if results[name] == 2 else 'FAIL')} ({time.time() - started:.0f}s)")
        if results[name] == 1:
            break
    print("\nSummary: " + ", ".join(f"{n}={'PASS' if c == 0 else ('NOT RUN' if c == 2 else 'FAIL')}" for n, c in results.items()))
    return 1 if any(c == 1 for c in results.values()) else (2 if any(c == 2 for c in results.values()) else 0)


if __name__ == "__main__":
    sys.exit(main())
