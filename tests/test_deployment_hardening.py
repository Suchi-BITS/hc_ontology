"""Static checks on the deployment files: Docker Compose and Kubernetes.

These read YAML. They prove what the files SAY. They do not prove what a Docker daemon or a cluster DOES with
them: no container was started and no manifest was applied in this environment.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def docs(name: str):
    return [d for d in yaml.safe_load_all((ROOT / name).read_text(encoding="utf-8")) if d]


# ---- Docker Compose ----------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def compose():
    return load("docker_compose.yaml")


def test_compose_api_is_production_mode_and_cannot_be_opened_from_the_environment(compose):
    env = compose["services"]["api"]["environment"]
    assert env["ENVIRONMENT"] == "production"                     # a literal, not ${ENVIRONMENT:-...}
    assert env["ALLOW_OPEN_DEVELOPMENT_MODE"] == "false"           # a literal, not read from .env
    text = (ROOT / "docker_compose.yaml").read_text(encoding="utf-8")
    assert "ENVIRONMENT:-development" not in text
    assert "ALLOW_OPEN_DEVELOPMENT_MODE:-" not in text


def test_compose_default_policy_refuses_to_start_without_credentials(compose):
    """Apply the policy to exactly the settings the API container receives by default."""
    from core.security_policy import UNCONFIGURED, decide

    env = compose["services"]["api"]["environment"]
    decision = decide(environment=env["ENVIRONMENT"], credentials_configured=False,  # API_KEY defaults to empty and no credentials file is in the image
                      allow_open_development_mode=env["ALLOW_OPEN_DEVELOPMENT_MODE"] == "true")
    assert decision.mode == UNCONFIGURED and not decision.unauthenticated_admin


def test_compose_published_ports_are_loopback_by_default_and_overridable_on_purpose(compose):
    for service in ("neo4j", "api", "streamlit"):
        for port in compose["services"][service]["ports"]:
            assert re.match(r"^\$\{[A-Z0-9_]+_BIND:-127\.0\.0\.1\}:", port), f"{service}: {port} is not loopback-bound by default"


def test_compose_does_not_pass_the_hosts_development_environment_into_the_container(compose):
    env = compose["services"]["api"]["environment"]
    assert not str(env["ENVIRONMENT"]).startswith("$")


def test_the_development_override_is_explicit_and_small():
    dev = load("docker_compose.dev.yaml")
    api = dev["services"]["api"]["environment"]
    assert api["ENVIRONMENT"] == "development" and api["ALLOW_OPEN_DEVELOPMENT_MODE"] == "true"
    assert set(dev["services"]) == {"api"}
    assert "ports" not in dev["services"]["api"], "the override must not re-publish ports; they stay loopback-bound"
    header = (ROOT / "docker_compose.dev.yaml").read_text(encoding="utf-8")
    assert "127.0.0.1" in header and "Do NOT set API_BIND=0.0.0.0" in header


def test_the_base_compose_file_documents_both_commands():
    text = (ROOT / "docker_compose.yaml").read_text(encoding="utf-8")
    assert "docker_compose.dev.yaml" in text and "refuses to start" in text.lower() and "API_KEY" in text


def test_compose_still_requires_the_database_password():
    assert "NEO4J_PASSWORD:?" in (ROOT / "docker_compose.yaml").read_text(encoding="utf-8")


def test_env_example_opts_in_for_local_work_and_explains_it():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"(?m)^ALLOW_OPEN_DEVELOPMENT_MODE=true", text)
    assert re.search(r"(?m)^ENVIRONMENT=development", text)
    assert "SPARQL_QUERY_TIMEOUT_SECONDS" in text


# ---- Kubernetes ------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def manifests():
    return docs("k8s/deployment.yaml")


def kind(manifests, name):
    return [m for m in manifests if m["kind"] == name]


@pytest.fixture(scope="module")
def pod(manifests):
    return kind(manifests, "Deployment")[0]["spec"]["template"]["spec"]


@pytest.fixture(scope="module")
def container(pod):
    return pod["containers"][0]


def test_k8s_image_is_pinned_not_latest(container):
    image = container["image"]
    assert ":latest" not in image
    assert re.search(r":\d+\.\d+\.\d+$", image) or "@sha256:" in image, f"{image} is not an explicit version tag or digest"


def test_k8s_image_tag_matches_the_project_version(container):
    version = re.search(r'(?m)^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    assert container["image"].endswith(f":{version}") or "@sha256:" in container["image"]


def test_k8s_pod_runs_as_non_root_with_the_images_user(pod):
    sc = pod["securityContext"]
    assert sc["runAsNonRoot"] is True and sc["runAsUser"] == 10001
    assert sc["seccompProfile"]["type"] == "RuntimeDefault"
    assert "--uid 10001" in (ROOT / "Dockerfile").read_text(encoding="utf-8")  # the uid exists in the image


def test_k8s_container_drops_privileges(container):
    sc = container["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"] and "add" not in sc["capabilities"]
    assert not sc.get("privileged")


def test_k8s_read_only_filesystem_has_the_writable_paths_it_needs(pod, container):
    mounts = {m["mountPath"] for m in container["volumeMounts"]}
    assert {"/tmp", "/app/validation_reports"} <= mounts
    names = {v["name"] for v in pod["volumes"]}
    assert {m["name"] for m in container["volumeMounts"]} <= names
    assert all("emptyDir" in v for v in pod["volumes"])


def test_k8s_service_account_token_is_not_mounted(pod):
    assert pod["automountServiceAccountToken"] is False


def test_k8s_has_resource_requests_and_limits(container):
    r = container["resources"]
    assert {"cpu", "memory"} <= set(r["requests"]) and {"cpu", "memory"} <= set(r["limits"])


def test_k8s_tracing_is_off_by_default_in_production(manifests):
    cfg = kind(manifests, "ConfigMap")[0]["data"]
    assert cfg["ENVIRONMENT"] == "production"
    assert cfg["LANGCHAIN_TRACING_V2"] == "false"
    assert cfg["OTEL_ENABLED"] == "false"
    assert cfg["ALLOW_OPEN_DEVELOPMENT_MODE"] == "false"


def test_k8s_contains_no_secret_object_and_no_secret_values(manifests):
    assert kind(manifests, "Secret") == [], "a Secret with empty values would overwrite a real one on apply"
    text = (ROOT / "k8s" / "deployment.yaml").read_text(encoding="utf-8")
    assert "stringData" not in text
    for pattern in (r"sk-[A-Za-z0-9_-]{20,}", r"lsv2_[A-Za-z0-9_]{20,}", r"hck_[A-Za-z0-9_-]{20,}"):
        assert not re.search(pattern, text)
    cfg = kind(manifests, "ConfigMap")[0]["data"]
    assert not [k for k in cfg if any(w in k for w in ("PASSWORD", "API_KEY", "SECRET", "TOKEN"))]


def test_k8s_secrets_are_referenced_externally(container):
    refs = [e["secretRef"]["name"] for e in container["envFrom"] if "secretRef" in e]
    assert refs == ["healthcare-ontology-secrets"]


def test_k8s_header_documents_the_assumptions():
    head = "".join((ROOT / "k8s" / "deployment.yaml").read_text(encoding="utf-8").splitlines(keepends=True)[:14])
    for needle in ("REPLACE_WITH_OWNER", "latest", "kubectl", "refuses to start", "Neo4j"):
        assert needle in head, needle


def test_cd_pipeline_no_longer_publishes_a_latest_tag_and_matches_the_manifest():
    cd = (ROOT / ".github" / "workflows" / "cd.yml").read_text(encoding="utf-8")
    assert "value=latest" not in cd
    assert '"Secret"' not in cd  # the manifest check no longer expects a Secret object


def test_dockerfile_image_still_runs_as_non_root_with_a_healthcheck():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"(?m)^USER app", text) and "HEALTHCHECK" in text
