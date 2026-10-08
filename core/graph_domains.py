"""Graph domains: which Neo4j labels belong to which kind of state, and what may delete them.

One Neo4j database holds several kinds of state with different owners and lifecycles.
Keeping them apart by label (Neo4j Community has a single user database) is what
lets the semantic projection be rebuilt without touching anything else.

    DOMAIN KNOWLEDGE  derived from RDF   rebuildable at any time   (:Resource, :OntologyClass)
    OPERATIONAL META  derived            rebuildable                (:ProjectionMeta)
    SEMANTIC INDEX    derived from RDF   rebuildable (embeddings)   (:OntologyConcept)
    APPLICATION DATA  user-supplied      NOT rebuildable            (:Document, :DocumentSection)
    AGENT MEMORY      produced at runtime NOT rebuildable           (:AgentSession, :AgentTurn, ...)

Only the first two are owned by the RDF projection. No projection operation may
delete or modify a label that is not listed in ``PROJECTION_LABELS``.
"""

from __future__ import annotations

from core.config import get_settings

PROJECTION_LABELS = ("Resource", "OntologyClass", "ProjectionMeta")
SEMANTIC_INDEX_LABELS = ("OntologyConcept",)
APPLICATION_LABELS = ("Document", "DocumentSection")
AGENT_MEMORY_LABELS = ("AgentSession", "AgentTurn", "AgentEvent", "AgentProcedure", "SessionSummary")

from core.security_policy import NON_PRODUCTION_ENVIRONMENTS as _DEVELOPMENT_ENVIRONMENTS  # one definition of "development"


class ResetNotAllowed(RuntimeError):
    """A destructive development operation was attempted where it is not permitted."""


def reset_allowed() -> bool:
    """True only in a development-type environment AND with an explicit opt-in flag."""
    settings = get_settings()
    return (
        str(settings.get("environment", "")).lower() in _DEVELOPMENT_ENVIRONMENTS
        and bool(settings.get("allow_projection_reset", False))
    )


def require_demo_allowed() -> None:
    """Loading demo data into Neo4j is a development convenience: never in production, never implicitly."""
    settings = get_settings()
    env = str(settings.get("environment", "")).lower()
    if env not in _DEVELOPMENT_ENVIRONMENTS:
        raise ResetNotAllowed(
            f"Demo seeding is disabled in ENVIRONMENT={env!r}; it is available only in development environments."
        )
    if not settings.get("allow_demo_seed", False):
        raise ResetNotAllowed(
            "Demo seeding requires ALLOW_DEMO_SEED=true (development only). There is no HTTP endpoint for it."
        )


def require_reset_allowed() -> None:
    settings = get_settings()
    env = str(settings.get("environment", "")).lower()
    if env not in _DEVELOPMENT_ENVIRONMENTS:
        raise ResetNotAllowed(
            f"Projection reset is disabled in ENVIRONMENT={env!r}. "
            "It is available only in development environments."
        )
    if not settings.get("allow_projection_reset", False):
        raise ResetNotAllowed(
            "Projection reset requires ALLOW_PROJECTION_RESET=true (development only). "
            "It removes only the RDF projection labels "
            f"{PROJECTION_LABELS}; agent memory, documents and embeddings are never touched."
        )
