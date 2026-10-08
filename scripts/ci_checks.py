"""Repository hygiene checks that CI runs on every push. Standard library only, no dependencies, no network.

    python scripts/ci_checks.py            # all checks; exit 1 if any finding
    python scripts/ci_checks.py secrets    # one check (names below)

Checks
------
  files      a tracked .env, credentials file, key, virtual environment or bytecode
  secrets    key-shaped strings (OpenAI, LangSmith, this project's API keys, AWS, GitHub, private keys) and a
             non-placeholder NEO4J_PASSWORD in anything that would be committed
  images     an image reference with the `latest` tag (or no tag) in Dockerfile, Compose, Kubernetes, workflows
  docker     the Dockerfile and Compose files: non-root user, healthcheck, no privileged/host networking, .dockerignore
  workflows  least-privilege permissions, no pull_request_target, no real AI credentials in the normal build
  assertions weak test assertions (`or True`, `>= 0`, `len(x) > 0`, `is not None` alone, a constant)
  docs       stale suite-size claims, retired names and architecture, wrong counts, dead links and paths

A line carrying `pragma: allowlist secret` is skipped by the secret scan (for deliberate fake keys in tests).
Each check is a function taking the repository root and returning findings, so the tests can feed it bad input.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRAGMA = "pragma: allowlist secret"
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache", ".ruff_cache"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".json", ".ttl", ".owl", ".csv", ".http", ".example", ".cfg",
                 ".ini", ".rq", ".nt", ".sh", ".env", ""}


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.check}] {where}: {self.message}"


# ---- which files --------------------------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> list[str] | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line for line in done.stdout.splitlines() if line]


def tracked(root: Path = ROOT) -> list[str]:
    """Files in the git index (what is committed). Falls back to a walk outside a repository."""
    listed = _git(root, "ls-files")
    if listed is not None:
        return listed
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()
                  and not (set(p.relative_to(root).parts) & SKIP_DIRS))


def committable(root: Path = ROOT) -> list[str]:
    """Tracked files plus untracked ones that are not ignored: everything a `git add -A` would publish."""
    listed = _git(root, "ls-files", "-co", "--exclude-standard")
    return listed if listed is not None else tracked(root)


def read(root: Path, rel: str) -> str | None:
    path = root / rel
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2_000_000:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


# ---- 1. files that must never be tracked ----------------------------------------------------------------------------

FORBIDDEN = [
    (re.compile(r"(^|/)\.env$"), "a real .env file"),
    (re.compile(r"(^|/)\.env\.(?!example$)[^/]+$"), "an environment file (only .env.example may be committed)"),
    (re.compile(r"(^|/)\.?credentials(\.json)?$|\.credentials\.json$"), "an API credentials file"),
    (re.compile(r"\.(pem|key|p12|pfx)$"), "a key or certificate file"),
    (re.compile(r"(^|/)(venv|\.venv|env)/"), "a virtual environment"),
    (re.compile(r"(^|/)__pycache__/|\.py[co]$"), "Python bytecode"),
    (re.compile(r"(^|/)\.pytest_cache/"), "a pytest cache"),
    (re.compile(r"(^|/)secrets?/|\.secret$|(^|/)\.streamlit/secrets\.toml$"), "a secrets file"),
]


def check_files(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    for rel in files if files is not None else committable(root):
        for pattern, what in FORBIDDEN:
            if pattern.search(rel):
                out.append(Finding("files", rel, 0, f"{what} must not be committed"))
                break
    return out


# ---- 2. secrets ------------------------------------------------------------------------------------------------------------

SECRET_PATTERNS = [
    ("an OpenAI-style API key", re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}")),
    ("a LangSmith API key", re.compile(r"lsv2_(?:pt|sk)_[A-Za-z0-9_]{20,}")),
    ("one of this project's API keys", re.compile(r"(?<![A-Za-z0-9])hck_[A-Za-z0-9_\-]{20,}")),
    ("an AWS access key id", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("a GitHub token", re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}")),
    ("a private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
]
PASSWORD_LINE = re.compile(r"""NEO4J_PASSWORD\s*[:=]\s*["']?([^\s"'#]*)""")
PASSWORD_OK = re.compile(r"(?i)^(<.*>|\$\{.*\}|\$[A-Za-z_]+|ci-only[-A-Za-z0-9]*|\.{3}|change-?me|your.*|x+|)$")
PLACEHOLDER_WORDS = ("placeholder", "replace", "your_", "your-", "example", "dummy", "fake", "invalid", "redacted", "changeme")


def secret_findings(rel: str, text: str) -> list[Finding]:
    out = []
    for number, line in enumerate(text.splitlines(), start=1):
        if PRAGMA in line:
            continue
        for what, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                if not any(word in match.group(0).lower() for word in PLACEHOLDER_WORDS):
                    out.append(Finding("secrets", rel, number, f"looks like {what}"))
        for match in PASSWORD_LINE.finditer(line) if not rel.endswith(".py") else ():   # code builds .env lines; real passwords live in env-style files
            value = match.group(1)
            if not PASSWORD_OK.match(value) and not value.endswith("?") and "NEO4J_PASSWORD:?" not in line:
                out.append(Finding("secrets", rel, number, "a NEO4J_PASSWORD with a real-looking value (use a placeholder, or a `ci-only-` value)"))
    return out


def check_secrets(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    for rel in files if files is not None else committable(root):
        text = read(root, rel)
        if text is not None:
            out += secret_findings(rel, text)
    return out


# ---- 3. image tags ---------------------------------------------------------------------------------------------------------------

def image_findings(rel: str, text: str) -> list[Finding]:
    out = []
    name = rel.rsplit("/", 1)[-1]
    stages: set[str] = set()                      # `FROM builder` refers to an earlier stage, not to an image
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0] if name != "Dockerfile" or not raw.lstrip().startswith("#") else ""
        ref = None
        m = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, re.I) if name == "Dockerfile" or name.startswith("Dockerfile") else None
        if m:
            image = m.group(1)
            if image.lower() != "scratch" and image not in stages:
                ref = image
            words = line.split()
            if len(words) >= 2 and words[-2].lower() == "as":      # `FROM x AS name` declares a stage called `name`
                stages.add(words[-1])
        m = re.match(r"\s*-?\s*image:\s*['\"]?([^\s'\"]+)", line)
        if m and rel.endswith((".yaml", ".yml")):
            ref = m.group(1)
        if ref and not ref.startswith(("$", "{")):
            if "@sha256:" in ref:
                continue
            tag = ref.rsplit(":", 1)[1] if ":" in ref.rsplit("/", 1)[-1] else ""
            if tag in ("", "latest"):
                out.append(Finding("images", rel, number, f"image '{ref}' has {'no tag' if not tag else 'the latest tag'}: pin a version or a digest"))
        if re.search(r"value=latest|:latest\b", line) and not any(f.line == number for f in out):
            out.append(Finding("images", rel, number, "references a ':latest' tag"))
    return out


def check_images(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    for rel in files if files is not None else committable(root):
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("Dockerfile") or name.startswith(("docker_compose", "docker-compose", "compose")) or rel.startswith((".github/workflows/", "k8s/")):
            text = read(root, rel)
            if text:
                out += image_findings(rel, text)
    return out


# ---- 4. Docker configuration ------------------------------------------------------------------------------------------------------

def dockerfile_findings(rel: str, text: str) -> list[Finding]:
    out = []
    users = re.findall(r"(?mi)^\s*USER\s+(\S+)", text)
    if not users or users[-1].lower() in ("root", "0"):
        out.append(Finding("docker", rel, 0, "the final stage must run as a non-root USER"))
    if not re.search(r"(?mi)^\s*HEALTHCHECK\s+(?!NONE)", text):
        out.append(Finding("docker", rel, 0, "no HEALTHCHECK"))
    for number, line in enumerate(text.splitlines(), start=1):
        if re.match(r"\s*ADD\s+https?://", line, re.I):
            out.append(Finding("docker", rel, number, "ADD from a URL: use a pinned, verified download"))
        if re.match(r"\s*(COPY|ADD)\s+.*\.env(\s|$)", line, re.I) and ".env.example" not in line:
            out.append(Finding("docker", rel, number, "copies an .env file into the image"))
        if re.search(r"pip install(?!.*(-c|--constraint))(?=.*requirements)", line):
            out.append(Finding("docker", rel, number, "pip install without the constraints file"))
    return out


def compose_findings(rel: str, text: str) -> list[Finding]:
    out = []
    for number, line in enumerate(text.splitlines(), start=1):
        code = line.split("#", 1)[0]
        if re.search(r"privileged:\s*true", code):
            out.append(Finding("docker", rel, number, "privileged container"))
        if re.search(r"network_mode:\s*['\"]?host", code):
            out.append(Finding("docker", rel, number, "host networking"))
        if re.search(r"/var/run/docker\.sock", code):
            out.append(Finding("docker", rel, number, "mounts the Docker socket"))
        if re.search(r"cap_add:", code):
            out.append(Finding("docker", rel, number, "adds Linux capabilities"))
        m = re.match(r"\s*-\s*['\"]?(?P<p>(?:[^'\"\s:]+:)?\d+:\d+)['\"]?\s*$", code)   # [host_ip:]host_port:container_port
        if m and not m.group("p").startswith(("127.0.0.1", "${", "[::1]", "localhost")):
            out.append(Finding("docker", rel, number, "a published port bound to every interface by default"))
    if rel.endswith("docker_compose.yaml"):
        if re.search(r"ENVIRONMENT:\s*\$\{[^}]*development", text) or re.search(r"ALLOW_OPEN_DEVELOPMENT_MODE:\s*['\"]?true", text):
            out.append(Finding("docker", rel, 0, "the default Compose file must be production-mode (open mode belongs in docker_compose.dev.yaml only)"))
    return out


def dockerignore_findings(text: str) -> list[Finding]:
    lines = {l.strip() for l in text.splitlines()}
    return [Finding("docker", ".dockerignore", 0, f"does not exclude {needed}") for needed in (".env", ".git", "venv", ".credentials.json")
            if needed not in lines]


def check_docker(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    names = files if files is not None else committable(root)
    for rel in names:
        name = rel.rsplit("/", 1)[-1]
        text = None
        if name == "Dockerfile":
            text = read(root, rel)
            out += dockerfile_findings(rel, text or "")
        elif name.startswith(("docker_compose", "docker-compose")) and name.endswith((".yaml", ".yml")) and ".dev." not in name:
            out += compose_findings(rel, read(root, rel) or "")
        elif name.startswith(("docker_compose", "docker-compose")) and ".dev." in name:
            out += [f for f in compose_findings(rel, read(root, rel) or "") if "production-mode" not in f.message]
    if ".dockerignore" in names:
        out += dockerignore_findings(read(root, ".dockerignore") or "")
    elif any(n == "Dockerfile" for n in names):
        out.append(Finding("docker", ".dockerignore", 0, "missing: the build context would include .env, .git and the virtualenv"))
    return out


# ---- 5. workflows -----------------------------------------------------------------------------------------------------------------

AI_SECRET = re.compile(r"secrets\.(OPENAI|LANGCHAIN|LANGSMITH)[A-Z_]*", re.I)


def workflow_findings(rel: str, text: str) -> list[Finding]:
    out = []
    live = rel.endswith("live-ai.yml")
    if re.search(r"(?m)^\s*pull_request_target\s*:", text):
        out.append(Finding("workflows", rel, 0, "pull_request_target runs untrusted code with secrets"))
    if not live and AI_SECRET.search(text):
        out.append(Finding("workflows", rel, 0, "the normal build must never use OpenAI or LangSmith secrets; use the manual live-ai workflow"))
    if not live and re.search(r"(?m)^\s*(OPENAI_API_KEY|LANGCHAIN_API_KEY|LANGSMITH_API_KEY)\s*:\s*\S", text):
        out.append(Finding("workflows", rel, 0, "the normal build sets an AI credential variable"))
    if not re.search(r"(?m)^permissions:", text):
        out.append(Finding("workflows", rel, 0, "no top-level `permissions:` block (default token rights are broader than needed)"))
    if live:
        triggers = re.search(r"(?ms)^on:\s*\n(.*?)(?=^\S)", text)
        block = triggers.group(1) if triggers else ""
        if re.search(r"^\s*(push|pull_request)\s*:", block, re.M) or "workflow_dispatch" not in block:
            out.append(Finding("workflows", rel, 0, "the live AI workflow must be manual (workflow_dispatch only)"))
    return out


def check_workflows(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    for rel in files if files is not None else committable(root):
        if rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml")):
            out += workflow_findings(rel, read(root, rel) or "")
    return out


# ---- 6. weak assertions -----------------------------------------------------------------------------------------------------------

def weak_assertion(test: ast.expr) -> str | None:
    """A reason this assert cannot fail for a meaningful reason, or None."""
    if isinstance(test, ast.Constant) and bool(test.value) is True:
        return "asserts a constant"
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        if any(isinstance(v, ast.Constant) and bool(v.value) is True for v in test.values):
            return "a disjunct is the constant True"
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, right, left = test.ops[0], test.comparators[0], test.left
        const = isinstance(right, ast.Constant)
        if isinstance(op, ast.GtE) and const and right.value == 0:
            return ">= 0 is true for every length and count"
        is_len = isinstance(left, ast.Call) and getattr(left.func, "id", "") == "len"
        if is_len and const and ((isinstance(op, ast.Gt) and right.value == 0) or (isinstance(op, ast.GtE) and right.value == 1)):
            return "len(...) > 0 says only that something exists, not what it is"
        if isinstance(op, ast.IsNot) and const and right.value is None:
            return "'is not None' alone does not say what the value is"
    return None


def assertion_findings(rel: str, source: str) -> list[Finding]:
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Finding("assertions", rel, exc.lineno or 0, "does not parse")]
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            reason = weak_assertion(node.test)
            if reason:
                out.append(Finding("assertions", rel, node.lineno, f"{reason}: assert {ast.unparse(node.test)[:70]}"))
    return out


def check_assertions(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    out = []
    for rel in files if files is not None else committable(root):
        if rel.startswith("tests/") and rel.endswith(".py") and "/" not in rel[len("tests/"):] and rel.rsplit("/", 1)[-1].startswith("test_"):
            out += assertion_findings(rel, read(root, rel) or "")
    return out


# ---- 7. documentation -------------------------------------------------------------------------------------------------------------

# Documents that record a dated run or an older state on purpose; every other document describes the CURRENT project.
HISTORICAL = {"docs/fresh-clone-verification.md", "docs/NEO4J_DESKTOP_LIVE_VERIFICATION.md", "docs/AI_LAYER_LIVE_VERIFICATION.md",
              "FINAL_INDEPENDENT_AUDIT.md", "PROJECT_ARCHITECTURE_AND_BOOK_READINESS_AUDIT.md", "BOOK_REFERENCE_GAP_ANALYSIS.md",
              "COURSE_SETUP.md", "COURSE_STRUCTURE.md"}
LEGACY_PREFIXES = ("docs/UDEMY_", "docs/YOUTUBE_")


def current_docs(files: list[str]) -> list[str]:
    docs = []
    for rel in files:
        if not rel.endswith(".md") or rel in HISTORICAL or rel.startswith(LEGACY_PREFIXES):
            continue
        if re.fullmatch(r"P\d+\.md", rel) or rel.startswith("agents/"):
            continue
        if rel in ("readme.md", "system_design.md", "graph_schema_design.md") or rel.startswith("docs/"):
            docs.append(rel)
    return docs


# Wording that states the size or outcome of the whole test suite. Such a number is stale the day after it is written:
# say how to count (`pytest --collect-only -q`), or put it in a dated record (HISTORICAL).
SUITE_CLAIM = re.compile(r"(?i)(?:~\s?\d[\d,]*\s+tests\b|\b\d[\d,]{2,}\s+(?:tests\s+(?:pass|run)|passed)\b|\babout\s+\d+\s+tests\b"
                         r"|\b\d+\s+expected failures?\b|\bwhole suite,\s*~?\d+)")
# Names and ideas that no longer describe this project (retired artifacts and settings).
RETIRED = [
    (re.compile(r"\bhealthcare_ontology\.owl\b"), "the combined healthcare_ontology.owl no longer exists (schema: ontology/healthcare_schema.ttl, data: data/sample_data.ttl)"),
    (re.compile(r"\bOWL_FILE_PATH\b"), "OWL_FILE_PATH was replaced by ONTOLOGY_SCHEMA_FILE and SAMPLE_DATA_FILE"),
    (re.compile(r"\bAUTH_MODE\b"), "AUTH_MODE was replaced by ALLOW_OPEN_DEVELOPMENT_MODE"),
    (re.compile(r"/neo4j/seed-demo"), "the /neo4j/seed-demo endpoint was removed"),
    (re.compile(r"\bexecute_with_timeout\b"), "execute_with_timeout was replaced by the process-based SPARQL limit"),
]
# A line that is explicitly telling the history is allowed to name a retired thing.
HISTORY_MARK = re.compile(r"(?i)\b(was|were|used to|no longer|removed|replaced|retired|previously|before|old(er)?|former(ly)?|instead of|renamed|historical|legacy)\b")


def doc_findings(rel: str, text: str) -> list[Finding]:
    out = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if SUITE_CLAIM.search(line):
            out.append(Finding("docs", rel, number, "states the size/outcome of the whole test suite (stale on the next commit): "
                                                    "say how to count it instead, or move it to a dated record"))
        for pattern, why in RETIRED:
            if pattern.search(line) and not HISTORY_MARK.search(line):
                out.append(Finding("docs", rel, number, f"names a retired thing: {why}"))
    return out


def count_claim_findings(root: Path, docs: list[str]) -> list[Finding]:
    """Numeric claims about the repository that can be checked without any dependency."""
    out = []
    rq = len(list((root / "sparql").glob("*.rq")))
    invalid = len([p for p in (root / "data" / "invalid_source").glob("*") if p.is_dir()]) if (root / "data" / "invalid_source").is_dir() else 0
    claims = [
        (re.compile(r"\b(\d+)\s+competency questions\b", re.I), rq, "competency questions (sparql/*.rq)"),
        (re.compile(r"\b(\d+)\s+(?:deliberately\s+)?(?:broken|invalid)\s+(?:source\s+)?(?:tables|cases|fixtures)\b", re.I), invalid, "invalid source cases (data/invalid_source/)"),
    ]
    for rel in docs:
        text = read(root, rel) or ""
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern, actual, what in claims:
                for m in pattern.finditer(line):
                    if int(m.group(1)) != actual and actual:
                        out.append(Finding("docs", rel, number, f"claims {m.group(1)} {what}; there are {actual}"))
    return out


LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-*]+)+/?)`")


def reference_findings(root: Path, rel: str, text: str, top: set[str]) -> list[Finding]:
    out = []
    base = (root / rel).parent
    for number, line in enumerate(text.splitlines(), start=1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.\-]*:", target) or target.startswith("#"):
                continue
            if not (base / target).resolve().exists():
                out.append(Finding("docs", rel, number, f"links to {target}, which does not exist"))
        for token in BACKTICK_PATH.findall(line):
            if token.split("/")[0] not in top or "<" in token or ">" in token:
                continue
            if "*" in token:
                if not list(root.glob(token)):
                    out.append(Finding("docs", rel, number, f"names {token}, which matches nothing"))
            elif not (root / token).exists() and not token.startswith(("tmp/", "build/")):
                out.append(Finding("docs", rel, number, f"names {token}, which does not exist"))
    return out


def check_docs(root: Path = ROOT, files: list[str] | None = None) -> list[Finding]:
    names = files if files is not None else committable(root)
    docs = current_docs(names)
    top = {p.name for p in root.iterdir() if not p.name.startswith(".")}
    out = []
    for rel in docs:
        text = read(root, rel) or ""
        out += doc_findings(rel, text)
        out += reference_findings(root, rel, text, top)
    out += count_claim_findings(root, docs)
    return out


# ---- driver -----------------------------------------------------------------------------------------------------------------------

CHECKS = {
    "files": check_files, "secrets": check_secrets, "images": check_images, "docker": check_docker,
    "workflows": check_workflows, "assertions": check_assertions, "docs": check_docs,
}


def run(names: list[str] | None = None, root: Path = ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for name in names or list(CHECKS):
        findings += CHECKS[name](root)
    return findings


def main(argv: list[str]) -> int:
    unknown = [a for a in argv if a not in CHECKS]
    if unknown:
        print(f"unknown check(s) {unknown}; choose from {sorted(CHECKS)}", file=sys.stderr)
        return 2
    names = argv or list(CHECKS)
    total = 0
    for name in names:
        found = CHECKS[name](ROOT)
        print(f"{'FAIL' if found else 'ok  '}  {name:<10} {len(found)} finding(s)")
        for f in found:
            print(f"      {f}")
        total += len(found)
    print(f"\n{'CHECKS FAILED' if total else 'ALL CHECKS PASSED'} ({total} finding(s))")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
