"""THE security policy: one pure function that decides how the API authenticates and authorizes.

No other module may decide "is this server open?" on its own. `core/security.py` asks this module, and
`tests/test_security_policy.py` enumerates every combination of the inputs and proves the invariant:

    production-like environment  AND  no credentials  =>  never open, never admin

Environments
------------
  development   ENVIRONMENT in {development, dev, local}
  testing       ENVIRONMENT in {test, testing}
  production    anything else, including a typo and an unset value (fail closed)

Behaviour
---------
  credentials configured        enforced everywhere: every request must authenticate
  no credentials, development   open ONLY if ALLOW_OPEN_DEVELOPMENT_MODE=true, else refuse to start
  no credentials, testing       same as development
  no credentials, production    refuse to start; ALLOW_OPEN_DEVELOPMENT_MODE is ignored and reported

  RBAC_ENABLED=false            honoured in development and testing only; ignored in production
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEVELOPMENT_ENVIRONMENTS = frozenset({"development", "dev", "local"})
TESTING_ENVIRONMENTS = frozenset({"test", "testing"})

NON_PRODUCTION_ENVIRONMENTS = DEVELOPMENT_ENVIRONMENTS | TESTING_ENVIRONMENTS

ENFORCED = "enforced"
OPEN = "development-open"
UNCONFIGURED = "unconfigured"


def classify_environment(name: str | None) -> str:
    value = (name or "").strip().lower()
    if value in DEVELOPMENT_ENVIRONMENTS:
        return "development"
    if value in TESTING_ENVIRONMENTS:
        return "testing"
    return "production"


def is_non_production(name: str | None) -> bool:
    """The one definition of 'a place where development conveniences may exist'. Unknown names are production."""
    return classify_environment(name) != "production"


@dataclass(frozen=True)
class SecurityDecision:
    mode: str                  # ENFORCED | OPEN | UNCONFIGURED
    environment_class: str     # development | testing | production
    authorization_enforced: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unauthenticated_admin(self) -> bool:
        return self.mode == OPEN


def decide(*, environment: str | None, credentials_configured: bool, allow_open_development_mode: bool,
           rbac_enabled: bool = True) -> SecurityDecision:
    env_class = classify_environment(environment)
    non_production = env_class in ("development", "testing")
    warnings: list[str] = []

    if credentials_configured:
        mode = ENFORCED
    elif non_production and allow_open_development_mode:
        mode = OPEN
        warnings.append(
            "AUTHENTICATION IS DISABLED (ALLOW_OPEN_DEVELOPMENT_MODE=true): every request runs as 'local-developer' "
            "with the admin role. Create a credential to enforce authentication."
        )
    else:
        mode = UNCONFIGURED

    if allow_open_development_mode and not non_production:
        warnings.append("ALLOW_OPEN_DEVELOPMENT_MODE is ignored outside development and testing environments.")
    if not rbac_enabled and not non_production:
        warnings.append("RBAC_ENABLED=false is ignored outside development and testing environments.")

    authorization = True if (rbac_enabled or not non_production) else False
    return SecurityDecision(mode=mode, environment_class=env_class, authorization_enforced=authorization,
                            warnings=tuple(warnings))


def refusal_message(environment: str | None) -> str:
    """The text an operator sees when the server refuses to start without credentials."""
    env_class = classify_environment(environment)
    base = f"ENVIRONMENT={environment!r} ({env_class}) requires authentication, but no credentials are configured. "
    fix = ("Create one with `python scripts/dev.py credential add --user <name> --tenant <tenant> --role <role>` "
           "(or set API_KEY), and keep the generated file private.")
    if env_class == "production":
        return base + fix
    return base + fix + (" For local work only, you may instead set ALLOW_OPEN_DEVELOPMENT_MODE=true "
                         "(authentication disabled, admin for everyone).")
