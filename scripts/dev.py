#!/usr/bin/env python3
"""One command line for the whole workflow, from a fresh clone to a running demo.

Uses only the Python standard library, so it runs before anything is installed.

    python scripts/dev.py quickstart      # setup -> doctor -> validate -> test -> demo   (no Docker, no API keys)
    python scripts/dev.py setup           # virtualenv + dependencies + .env
    python scripts/dev.py doctor          # what is installed, configured, reachable; and how to fix it
    python scripts/dev.py doctor --neo4j  # also connect to the configured Neo4j (for example Neo4j Desktop) and report
    python scripts/dev.py validate        # ontology, SHACL, projection checks
    python scripts/dev.py test            # the test suite (extra args go to pytest)
    python scripts/dev.py demo            # a guided tour of the system
    python scripts/dev.py up              # start Neo4j in Docker and wait until it is healthy
    python scripts/dev.py verify-neo4j    # read-only: connectivity, database, version, counts (add --projection to compare with the RDF)
    python scripts/dev.py load            # load the ontology/data into the CONFIGURED Neo4j (Neo4j Desktop or any bolt endpoint)
    python scripts/dev.py serve           # run the API on http://127.0.0.1:8000
    python scripts/dev.py down            # stop Docker services (add --volumes to delete the dev database)
    python scripts/dev.py lock            # refresh constraints.txt from the current virtualenv
    python scripts/dev.py credential add --user suchismita --tenant abhigya-ai-lab --role admin
                                          # create an API credential (the key is shown once)

On Linux/macOS `make <command>` does the same. On Windows use `python scripts/dev.py <command>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / "venv"
PY = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MIN_PYTHON = (3, 11)
TESTED_PYTHON = (3, 11)  # the version the Dockerfile, CI and the verification runs use

OK, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def say(message: str = "") -> None:
    print(message, flush=True)


def run(cmd, *, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    say("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, check=check, **kwargs)


def venv_python() -> Path:
    if not PY.exists():
        if sys.prefix != sys.base_prefix:  # dev.py itself is running inside a virtual environment: use that one
            return Path(sys.executable)
        raise SystemExit("No virtual environment yet. Run:  python scripts/dev.py setup")
    return PY


def read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_placeholder(value: str | None) -> bool:
    return not value or (value.startswith("<") and value.endswith(">"))


def compose_command() -> list[str] | None:
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if probe.returncode == 0:
            return ["docker", "compose", "-f", "docker_compose.yaml"]
    if shutil.which("docker-compose"):
        return ["docker-compose", "-f", "docker_compose.yaml"]
    return None


def docker_running() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, text=True).returncode == 0


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def pip_install(args: list[str]) -> None:
    """pip install into the project venv, surviving TLS-inspecting proxies and antivirus.

    Some networks (corporate proxies, antivirus HTTPS scanning) re-sign traffic with a CA that only the
    operating-system store trusts, so pip fails with CERTIFICATE_VERIFY_FAILED. Remedy, in order:
    1. plain install; 2. if (and only if) that failure occurs, install `pip-system-certs` with the two
    PyPI hosts trusted for that one command, which makes pip use the OS store from then on; 3. retry
    verified. The insecure step is announced, limited to PyPI hosts, and skipped when not needed.
    """
    base = [str(PY), "-m", "pip", "install", "--disable-pip-version-check"]

    def attempt(extra: list[str]) -> tuple[int, str]:
        proc = subprocess.Popen(
            base + extra + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        captured = []
        for line in proc.stdout:  # type: ignore[union-attr]
            print(line, end="", flush=True)
            captured.append(line)
        return proc.wait(), "".join(captured)

    say("$ " + " ".join(base + args))
    code, output = attempt([])
    if code == 0:
        return
    if "CERTIFICATE_VERIFY_FAILED" not in output:
        raise SystemExit(f"pip failed (exit {code}). See the output above.")

    say("\n!! TLS certificate verification failed. This usually means a proxy or antivirus re-signs HTTPS traffic.")
    say("!! Installing 'pip-system-certs' (uses the operating system's certificate store) with pypi.org and")
    say("!! files.pythonhosted.org trusted for that single step, then retrying with verification on.\n")
    hosts = ["--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org"]
    fix = subprocess.run(base + hosts + ["pip-system-certs"], cwd=ROOT)
    if fix.returncode == 0:
        code, output = attempt([])
        if code == 0:
            return
        say("\n!! Still failing with verification on; falling back to trusted PyPI hosts for this install.")
    code, output = attempt(hosts)
    if code != 0:
        raise SystemExit(
            "pip failed even with the PyPI hosts trusted. Check your network or proxy settings "
            "(pip config list; HTTPS_PROXY), then re-run setup."
        )


def ensure_env_file() -> None:
    """Create .env from .env.example with a generated local Neo4j password. Never overwrites."""
    target, template = ROOT / ".env", ROOT / ".env.example"
    if target.exists():
        say(".env already exists; leaving it unchanged.")
        return
    text = template.read_text(encoding="utf-8")
    password = secrets.token_urlsafe(18)
    text = re.sub(r"^NEO4J_PASSWORD=.*$", f"NEO4J_PASSWORD={password}", text, flags=re.M)
    text = re.sub(r"^OPENAI_API_KEY=.*$", "OPENAI_API_KEY=", text, flags=re.M)
    target.write_text(text, encoding="utf-8")
    say("Created .env with a generated NEO4J_PASSWORD (local development only; .env is git-ignored).")
    say("OPENAI_API_KEY is empty: set it only if you want natural-language queries, embeddings or the agent.")


def cmd_setup(_args) -> int:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; this is {sys.version.split()[0]}.")
    if sys.version_info[:2] > TESTED_PYTHON:
        say(f"NOTE: this project is tested on Python {TESTED_PYTHON[0]}.{TESTED_PYTHON[1]}; "
            f"{sys.version.split()[0]} should work but is not verified.")
    if not PY.exists():
        say(f"Creating virtual environment in {VENV_DIR.name}/ ...")
        venv.create(VENV_DIR, with_pip=True, clear=False)
    pip_install(["-r", "requirements-dev.txt", "-c", "constraints.txt"])
    ensure_env_file()
    (ROOT / "validation_reports").mkdir(exist_ok=True)
    say("\nSetup complete. Next:  python scripts/dev.py doctor   (or: quickstart)")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    results: list[tuple[str, str, str]] = []

    def check(status: str, name: str, detail: str = "") -> None:
        results.append((status, name, detail))

    py_ok = sys.version_info >= MIN_PYTHON
    untested = py_ok and sys.version_info[:2] > TESTED_PYTHON
    check(FAIL if not py_ok else (WARN if untested else OK), f"Python {sys.version.split()[0]}",
          f"need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+: install it from python.org" if not py_ok
          else (f"works but only {TESTED_PYTHON[0]}.{TESTED_PYTHON[1]} is verified" if untested else ""))

    if PY.exists() or sys.prefix != sys.base_prefix:
        interpreter = PY if PY.exists() else Path(sys.executable)
        check(OK, "virtual environment", str(VENV_DIR.name) + "/" if PY.exists() else f"active environment: {sys.prefix}")
        probe = subprocess.run(
            [str(interpreter), "-c", "import fastapi, rdflib, pyshacl, owlready2, neo4j, pytest, dotenv, langgraph"],
            capture_output=True, text=True, cwd=ROOT,
        )
        check(OK if probe.returncode == 0 else FAIL, "dependencies import",
              "" if probe.returncode == 0 else probe.stderr.strip().splitlines()[-1] + "  -> python scripts/dev.py setup")
    else:
        check(FAIL, "virtual environment", "missing -> python scripts/dev.py setup")

    for rel in ("ontology/healthcare_schema.ttl", "data/sample_data.ttl", "shapes/patient_shapes.ttl", "sparql/cq01_patients.rq", "constraints.txt"):
        check(OK if (ROOT / rel).is_file() else FAIL, rel, "" if (ROOT / rel).is_file() else "missing: re-clone the repository")

    env = read_env_file()
    if (ROOT / ".env").is_file():
        check(OK, ".env")
    else:
        check(WARN, ".env", "missing -> python scripts/dev.py setup (creates it)")
    env_name = (env.get("ENVIRONMENT") or "production").strip().lower()
    open_opt_in = (env.get("ALLOW_OPEN_DEVELOPMENT_MODE") or "").strip().lower() in ("true", "1", "yes")
    has_credentials = CREDENTIALS_FILE.is_file() or bool((env.get("API_KEY") or "").strip())
    if has_credentials:
        check(OK, "authentication", "credentials configured: every request must authenticate")
    elif env_name in ("development", "dev", "local", "test", "testing") and open_opt_in:
        check(INFO, "authentication", "open development mode (no credentials, everyone is admin): local use only")
    else:
        check(WARN, "authentication", "no credentials and open mode is off, so the API will refuse to start -> "
              "add ALLOW_OPEN_DEVELOPMENT_MODE=true with ENVIRONMENT=development to .env (local only), "
              "or: python scripts/dev.py credential add --user <you> --tenant <tenant> --role admin")
    check(OK if not is_placeholder(env.get("NEO4J_PASSWORD")) else WARN, "NEO4J_PASSWORD",
          "" if not is_placeholder(env.get("NEO4J_PASSWORD")) else "not set: needed to load the graph (setup generates one)")
    check(OK if not is_placeholder(env.get("OPENAI_API_KEY")) else INFO, "OPENAI_API_KEY",
          "" if not is_placeholder(env.get("OPENAI_API_KEY")) else "not set: optional (natural-language queries, embeddings, agent)")

    java = shutil.which("java")
    check(OK if java else WARN, "Java", "" if java else "not found: 6 OWL-reasoner tests will be skipped (install a JRE)")

    if docker_running():
        check(OK, "Docker daemon")
    elif shutil.which("docker"):
        check(INFO, "Docker daemon", "installed but not running (optional: only the Docker Neo4j/API path needs it)")
    else:
        check(INFO, "Docker", "not installed: optional. The reference path is a local Neo4j (for example Neo4j Desktop)")

    uri = urlparse(env.get("NEO4J_URI", "bolt://localhost:7687"))
    reachable = port_open(uri.hostname or "localhost", uri.port or 7687)
    check(OK if reachable else INFO, f"Neo4j at {uri.hostname}:{uri.port or 7687}",
          "" if reachable else "not reachable: optional for validate/test/demo. Start your Neo4j Desktop database (or `up` for Docker)")

    width = max(len(name) for _, name, _ in results)
    say()
    for status, name, detail in results:
        say(f"  [{status}] {name.ljust(width)}  {detail}")
    failed = [n for s, n, _ in results if s == FAIL]
    say()
    if getattr(args, "neo4j", False):
        say("Live Neo4j check (read-only):")
        code = run([venv_python(), "scripts/verify_neo4j.py"], check=False).returncode
        if code != 0:
            failed.append("neo4j")
    if failed:
        say("Doctor found problems: " + ", ".join(failed))
        return 1
    say("Ready. Try:  python scripts/dev.py validate   |   test   |   demo")
    return 0


# ---------------------------------------------------------------------------
# tasks run inside the virtual environment
# ---------------------------------------------------------------------------

def cmd_validate(args) -> int:
    extra = ["--reasoner"] if args.reasoner else []
    return run([venv_python(), "scripts/validate.py", *extra], check=False).returncode


def cmd_test(args) -> int:
    return run([venv_python(), "-m", "pytest", *args.pytest_args], check=False).returncode


def cmd_demo(args) -> int:
    extra = ["--neo4j"] if args.neo4j else []
    return run([venv_python(), "scripts/demo.py", *extra], check=False).returncode


def cmd_serve(_args) -> int:
    say("API on http://127.0.0.1:8000  (docs at /docs). Ctrl+C to stop.")
    return run([venv_python(), "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"], check=False).returncode


def cmd_load(args) -> int:
    extra = ["--dry-run"] if args.dry_run else ["--wait", str(args.wait), "--verify"]
    return run([venv_python(), "scripts/load_graph.py", *extra], check=False).returncode


def cmd_verify_neo4j(args) -> int:
    extra = [flag for flag, on in (("--projection", args.projection), ("--census", args.census)) if on]
    return run([venv_python(), "scripts/verify_neo4j.py", *extra], check=False).returncode


def cmd_lock(_args) -> int:
    frozen = subprocess.run([str(venv_python()), "-m", "pip", "freeze", "--exclude-editable"],
                            capture_output=True, text=True, cwd=ROOT, check=True).stdout
    lines = sorted((l for l in frozen.splitlines() if l and not l.startswith("#")), key=str.lower)
    header = ("# Exact versions this project was tested with. Used as pip constraints:\n"
              "#   pip install -r requirements.txt -c constraints.txt\n"
              "# Refresh after changing requirements: python scripts/dev.py lock\n")
    (ROOT / "constraints.txt").write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    say(f"Wrote constraints.txt ({len(lines)} packages).")
    return 0


# ---------------------------------------------------------------------------
# Docker services
# ---------------------------------------------------------------------------

def need_compose() -> list[str]:
    compose = compose_command()
    if compose is None:
        raise SystemExit("Docker Compose not found. Install Docker Desktop, or run your own Neo4j 5.x "
                         "and set NEO4J_URI / NEO4J_PASSWORD in .env.")
    if not docker_running():
        raise SystemExit("The Docker daemon is not running. Start Docker Desktop and retry.")
    if is_placeholder(read_env_file().get("NEO4J_PASSWORD")):
        raise SystemExit("NEO4J_PASSWORD is not set in .env. Run:  python scripts/dev.py setup")
    return compose


def cmd_up(_args) -> int:
    compose = need_compose()
    code = run([*compose, "up", "-d", "--wait", "neo4j"], check=False).returncode
    if code == 0:
        say("\nNeo4j is healthy: bolt://localhost:7687  browser http://localhost:7474  (user neo4j, password from .env)")
        say("Next:  python scripts/dev.py load")
    return code


def cmd_down(args) -> int:
    compose = need_compose()
    extra = ["--volumes"] if args.volumes else []
    if args.volumes:
        say("--volumes deletes the DEVELOPMENT Neo4j data volume. The graph is rebuilt from RDF by `load`.")
    return run([*compose, "down", *extra], check=False).returncode


# ---------------------------------------------------------------------------
# credentials (identity, role and tenant live on the server, never in request headers)
# ---------------------------------------------------------------------------

CREDENTIALS_FILE = ROOT / ".credentials.json"
KNOWN_ROLES = ("viewer", "analyst", "approver", "admin", "platform_admin")  # = core.authz.ROLE_PERMISSIONS


def _load_credentials() -> dict:
    if CREDENTIALS_FILE.is_file():
        return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    return {"credentials": []}


def _save_credentials(data: dict) -> None:
    CREDENTIALS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)  # no effect on Windows; the file holds hashes only
    except OSError:
        pass


def cmd_credential(args) -> int:
    data = _load_credentials()
    records = data.setdefault("credentials", [])
    if args.action == "list":
        if not records:
            say("No credentials. Without any, the server refuses to start unless ENVIRONMENT=development and ALLOW_OPEN_DEVELOPMENT_MODE=true.")
        for r in records:
            say(f"  {r['id']:<20} tenant={r['tenant_id']:<20} role={r['role']:<15} {r.get('display_name', '')}")
        return 0
    if not args.user:
        raise SystemExit("--user is required")
    if args.action == "remove":
        kept = [r for r in records if r["id"] != args.user]
        if len(kept) == len(records):
            raise SystemExit(f"No credential for '{args.user}'.")
        data["credentials"] = kept
        _save_credentials(data)
        say(f"Removed '{args.user}'. Its key no longer works.")
        return 0
    # add
    if not args.tenant or not args.role:
        raise SystemExit("--tenant and --role are required")
    if args.role not in KNOWN_ROLES:
        raise SystemExit(f"Unknown role '{args.role}'. Choose one of: {', '.join(KNOWN_ROLES)}")
    if any(r["id"] == args.user for r in records):
        raise SystemExit(f"A credential for '{args.user}' already exists. Remove it first (credential remove).")
    key = "hck_" + secrets.token_urlsafe(32)
    records.append({
        "id": args.user,
        "display_name": args.display_name or args.user,
        "tenant_id": args.tenant,
        "role": args.role,
        "key_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
    })
    _save_credentials(data)
    say(f"Credential created for '{args.user}' (tenant {args.tenant}, role {args.role}).")
    say("")
    say(f"    API key (shown ONCE, store it safely): {key}")
    say("")
    say("Send it as   X-API-Key: <key>   or   Authorization: Bearer <key>.")
    say(f"Only a hash is stored, in {CREDENTIALS_FILE.name} (git-ignored). With any credential present, every request must authenticate.")
    return 0


def cmd_quickstart(args) -> int:
    for name, fn in (("setup", cmd_setup), ("doctor", cmd_doctor), ("validate", cmd_validate),
                     ("test", cmd_test), ("demo", cmd_demo)):
        say(f"\n==================== {name} ====================")
        ns = argparse.Namespace(reasoner=False, pytest_args=["-q"], neo4j=False)
        code = fn(ns)
        if code != 0:
            say(f"\nquickstart stopped at '{name}' (exit {code}).")
            return code
    say("\nQuickstart finished. To add Neo4j:  up  ->  load  ->  demo --neo4j")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dev.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="create venv, install dependencies, create .env").set_defaults(fn=cmd_setup)
    p = sub.add_parser("doctor", help="diagnose the environment")
    p.add_argument("--neo4j", action="store_true", help="also connect to the configured Neo4j and report (read-only)")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("verify-neo4j", help="read-only check of the configured Neo4j (Neo4j Desktop or any bolt endpoint)")
    p.add_argument("--projection", action="store_true", help="also compare the database with the RDF projection")
    p.add_argument("--census", action="store_true", help="also list labels and relationship types")
    p.set_defaults(fn=cmd_verify_neo4j)
    p = sub.add_parser("validate", help="ontology, SHACL and projection checks")
    p.add_argument("--reasoner", action="store_true", help="also run the OWL reasoner (needs Java)")
    p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("test", help="run the test suite")
    p.add_argument("pytest_args", nargs=argparse.REMAINDER, help="arguments passed to pytest")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("demo", help="guided tour (works offline)")
    p.add_argument("--neo4j", action="store_true", help="also load and query Neo4j")
    p.set_defaults(fn=cmd_demo)
    sub.add_parser("serve", help="run the API locally").set_defaults(fn=cmd_serve)
    p = sub.add_parser("load", help="load the ontology/data into Neo4j")
    p.add_argument("--dry-run", action="store_true", help="plan only; no database")
    p.add_argument("--wait", type=int, default=60, help="seconds to wait for Neo4j")
    p.set_defaults(fn=cmd_load)
    sub.add_parser("up", help="start Neo4j in Docker").set_defaults(fn=cmd_up)
    p = sub.add_parser("down", help="stop Docker services")
    p.add_argument("--volumes", action="store_true", help="also delete the development database volume")
    p.set_defaults(fn=cmd_down)
    sub.add_parser("lock", help="refresh constraints.txt").set_defaults(fn=cmd_lock)
    p = sub.add_parser("credential", help="manage API credentials (identity, role, tenant)")
    p.add_argument("action", choices=["add", "list", "remove"])
    p.add_argument("--user", help="credential id, for example suchismita")
    p.add_argument("--tenant", help="tenant id, for example abhigya-ai-lab")
    p.add_argument("--role", help="one of: " + ", ".join(KNOWN_ROLES))
    p.add_argument("--display-name", help="human-readable name, for example 'Suchismita'")
    p.set_defaults(fn=cmd_credential)
    sub.add_parser("quickstart", help="setup, doctor, validate, test, demo").set_defaults(fn=cmd_quickstart)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
