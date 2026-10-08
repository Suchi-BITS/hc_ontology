"""The single security policy (core/security_policy.py): behaviour per environment, and the invariant.

INVARIANT: no combination of settings produces  unauthenticated + admin + production  without an explicit
opt-in, and the opt-in is not honoured in production at all.
"""

from __future__ import annotations

import itertools

import pytest

from core import security_policy as policy
from core.config import ConfigurationError, get_settings
from core.security import SecurityConfigurationError, security_mode, validate_security_configuration

ENVIRONMENTS = ["development", "dev", "local", "test", "testing", "production", "prod", "staging", "live",
                "Production", " production ", "", None, "develpment", "devel", "development ", "DEV", "TEST"]


# ---- the exhaustive matrix ---------------------------------------------------------------------------

@pytest.mark.parametrize("environment,credentials,flag,rbac", list(itertools.product(ENVIRONMENTS, [False, True], [False, True], [False, True])))
def test_no_combination_yields_unauthenticated_admin_in_production(environment, credentials, flag, rbac):
    d = policy.decide(environment=environment, credentials_configured=credentials, allow_open_development_mode=flag,
                      rbac_enabled=rbac)
    non_production = (environment or "").strip().lower() in policy.NON_PRODUCTION_ENVIRONMENTS
    if d.mode == policy.OPEN:
        # open requires ALL of: no credentials, a non-production environment, the explicit opt-in
        assert not credentials and non_production and flag
    if not non_production:
        assert d.mode != policy.OPEN
        assert d.authorization_enforced is True      # RBAC_ENABLED=false is ignored in production
        assert d.environment_class == "production"
    if credentials:
        assert d.mode == policy.ENFORCED             # credentials always win: nobody is anonymous
    assert d.unauthenticated_admin == (d.mode == policy.OPEN)


def test_unknown_and_unset_environments_fail_closed():
    for name in ("", None, "prod", "staging", "develpment", "Production"):
        d = policy.decide(environment=name, credentials_configured=False, allow_open_development_mode=True)
        assert d.mode == policy.UNCONFIGURED and d.environment_class == "production", name


def test_the_three_environments_behave_as_documented():
    table = {
        # (environment, credentials, opt-in) -> mode
        ("development", False, False): policy.UNCONFIGURED,
        ("development", False, True): policy.OPEN,
        ("development", True, False): policy.ENFORCED,
        ("testing", False, False): policy.UNCONFIGURED,
        ("testing", False, True): policy.OPEN,
        ("testing", True, True): policy.ENFORCED,
        ("production", False, False): policy.UNCONFIGURED,
        ("production", False, True): policy.UNCONFIGURED,
        ("production", True, False): policy.ENFORCED,
        ("production", True, True): policy.ENFORCED,
    }
    for (env, creds, flag), expected in table.items():
        got = policy.decide(environment=env, credentials_configured=creds, allow_open_development_mode=flag).mode
        assert got == expected, (env, creds, flag)


def test_the_opt_in_in_production_is_reported_not_obeyed():
    d = policy.decide(environment="production", credentials_configured=True, allow_open_development_mode=True)
    assert any("ignored outside development" in w for w in d.warnings)


# ---- through the real configuration path ----------------------------------------------------------------------

@pytest.fixture
def no_credentials(configure):
    configure(API_CREDENTIALS_FILE="", API_KEY="")


def test_an_unset_environment_means_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    get_settings.cache_clear()
    assert get_settings()["environment"] == "production"
    get_settings.cache_clear()


def test_production_refuses_to_start_without_credentials(configure, no_credentials):
    configure(ENVIRONMENT="production", ALLOW_OPEN_DEVELOPMENT_MODE="false")
    with pytest.raises(SecurityConfigurationError, match="requires authentication"):
        validate_security_configuration()


def test_production_refuses_to_start_even_with_the_opt_in(configure, no_credentials):
    """The opt-in cannot be set in production by accident or by mistake."""
    configure(ENVIRONMENT="production", ALLOW_OPEN_DEVELOPMENT_MODE="true")
    assert security_mode() == "unconfigured"
    with pytest.raises(SecurityConfigurationError):
        validate_security_configuration()


def test_a_misspelt_environment_is_production_and_refuses(configure, no_credentials):
    configure(ENVIRONMENT="develpment", ALLOW_OPEN_DEVELOPMENT_MODE="true")
    with pytest.raises(SecurityConfigurationError):
        validate_security_configuration()


def test_development_without_the_opt_in_refuses_and_says_how_to_opt_in(configure, no_credentials):
    configure(ENVIRONMENT="development", ALLOW_OPEN_DEVELOPMENT_MODE="false")
    with pytest.raises(SecurityConfigurationError, match="ALLOW_OPEN_DEVELOPMENT_MODE=true"):
        validate_security_configuration()


def test_development_with_the_opt_in_starts_and_warns_loudly(configure, no_credentials):
    configure(ENVIRONMENT="development", ALLOW_OPEN_DEVELOPMENT_MODE="true")
    warnings = validate_security_configuration()
    assert any("AUTHENTICATION IS DISABLED" in w and "ALLOW_OPEN_DEVELOPMENT_MODE" in w for w in warnings)


def test_the_opt_in_must_be_a_real_boolean(configure):
    for bad in ("ture", "enabled", "2", "tru"):
        configure(ALLOW_OPEN_DEVELOPMENT_MODE=bad)
        with pytest.raises(ConfigurationError, match="ALLOW_OPEN_DEVELOPMENT_MODE must be true or false"):
            get_settings()


def test_production_serves_nothing_without_credentials_whatever_the_flags(client, configure, no_credentials):
    configure(ENVIRONMENT="production", ALLOW_OPEN_DEVELOPMENT_MODE="true", RBAC_ENABLED="false")
    for path in ("/patients", "/ontology/classes", "/sparql"):
        response = client.get(path, headers={"X-Role": "admin", "X-API-Key": "anything"})
        assert response.status_code in (503, 404, 405), path
    assert client.post("/sparql", json={"query": "SELECT ?s WHERE { ?s ?p ?o }"}).status_code == 503
    assert client.post("/neo4j/load").status_code == 503


def test_open_mode_in_development_still_works_for_the_developer(client, configure, no_credentials):
    configure(ENVIRONMENT="development", ALLOW_OPEN_DEVELOPMENT_MODE="true")
    assert client.get("/patients").status_code == 200


def test_the_api_refuses_to_start_through_its_startup_hook_in_every_unsafe_case(configure, no_credentials):
    import api

    for env, flag in (("production", "true"), ("production", "false"), ("development", "false"), ("", "true")):
        configure(ENVIRONMENT=env, ALLOW_OPEN_DEVELOPMENT_MODE=flag)
        with pytest.raises(SecurityConfigurationError):
            api.on_startup()


def test_authorization_cannot_be_switched_off_in_production(configure, secure):
    configure(ENVIRONMENT="production", RBAC_ENABLED="false")
    from core.security import current_decision

    assert current_decision().authorization_enforced is True
    configure(ENVIRONMENT="development", RBAC_ENABLED="false")
    assert current_decision().authorization_enforced is False


# ---- one policy, no copies --------------------------------------------------------------------------------------

def test_no_other_module_keeps_its_own_list_of_development_environments():
    """Two definitions of "development" would be two policies. Everything derives from core/security_policy.py."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in list((root / "core").glob("*.py")) + list((root / "services").glob("*.py")) + list((root / "routers").glob("*.py")) + list((root / "enterprise").glob("*.py")):
        if path.name == "security_policy.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"development", "dev"' in text or "'development', 'dev'" in text:
            offenders.append(path.name)
    assert offenders == []


def test_the_policy_document_exists_and_names_all_three_environments():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "security-policy.md").read_text(encoding="utf-8")
    for needle in ("development", "testing", "production", "ALLOW_OPEN_DEVELOPMENT_MODE", "docker_compose.dev.yaml",
                   "SPARQL_QUERY_TIMEOUT_SECONDS"):
        assert needle in text, needle
