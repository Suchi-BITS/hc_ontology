"""Shared LangGraph state for the healthcare multi-agent system."""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

QueryType = Literal["cypher", "sparql", "ontology_only"]
RunStatus = Literal[
    "pending",
    "planning",
    "retrieving",
    "generating",
    "validating",
    "awaiting_approval",
    "executing",
    "responding",
    "completed",
    "failed",
    
    "rejected",
]


class AgentState(TypedDict, total=False):
    """Shared state passed between planner → ontology → query → validation →
    execution → response nodes (plus HITL / retry fields).
    """

    # Identity / session
    thread_id: str
    session_id: str
    question: str
    tenant_id: str
    ontology_id: str
    ontology_version: str
    user_id: str

    # Planner outputs
    plan: list[str]
    query_type: QueryType
    reasoning: str
    require_human_approval: bool
    max_retries: int

    # Memory (working / episodic / procedural / semantic)
    memory_bundle: dict[str, Any]
    memory_context: str
    working_context: str
    working_events: list[dict[str, Any]]
    matched_procedures: list[dict[str, Any]]
    meta_memory: dict[str, Any]

    # Ontology retrieval (semantic memory projection)
    ontology_context: str
    retrieved_concepts: list[dict[str, Any]]
    hybrid_meta: dict[str, Any]
    retrieval_meta: dict[str, Any]

    # Governance (provenance + abstention)
    provenance: dict[str, Any]
    refused: bool
    refusal_reason: Optional[str]
    confidence: float
    abstention_threshold: float
    confidence_signals: dict[str, float]
    structured_answer: dict[str, Any]

    # Query generation
    draft_query: str
    query_attempts: int

    # Validation
    validation_ok: bool
    validation_error: Optional[str]
    validation_stage: Optional[str]
    validated_query: str

    # Human-in-the-loop
    human_decision: Optional[Literal["approved", "rejected"]]
    human_feedback: Optional[str]

    # Execution
    results: list[Any]
    execution_error: Optional[str]

    # Response
    answer: str
    citations: list[str]
    status: RunStatus
    errors: list[str]
    trace: list[str]
    cost_usd: float
    blocked: bool
    guardrail_flags: list[str]
