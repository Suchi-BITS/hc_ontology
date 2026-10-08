"""Semantic memory — ontology concepts, schema, and document grounding."""

from __future__ import annotations

import logging
from typing import Any

from core.config import get_settings
from core.dependencies import get_ontology
from enterprise.retrieval_pipeline import retrieve_with_rerank

logger = logging.getLogger("healthcare_ontology.agent")


def retrieve_semantic_memory(
    question: str,
    *,
    pool_size: int | None = None,
    top_k: int | None = None,
    include_documents: bool = True,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Fuse hybrid concept retrieval with optional GraphRAG document sections."""
    settings = get_settings()
    pool_size = pool_size or int(settings.get("agent_retrieval_pool_size", 16))
    top_k = top_k or int(settings.get("agent_retrieval_top_k", 8))

    concepts: list[dict[str, Any]] = []
    hybrid_meta: dict[str, Any] = {}
    retrieval_meta: dict[str, Any] = {}
    document_sections: list[dict[str, Any]] = []

    try:
        pipeline = retrieve_with_rerank(question, pool_size=pool_size, top_k=top_k)
        concepts = pipeline.get("results") or []
        hybrid_meta = {
            "vector_count": pipeline.get("vector_count"),
            "graph_count": pipeline.get("graph_count"),
        }
        retrieval_meta = {
            "pool_size": len(pipeline.get("pool") or []),
            "error_budget": pipeline.get("error_budget"),
            "channels": pipeline.get("channels"),
        }
    except Exception as exc:
        logger.warning("Semantic concept retrieval failed: %s", exc)

    schema_excerpt = ""
    try:
        onto = get_ontology()
        classes = onto.get_classes()[:40]
        obj_props = onto.get_object_properties()[:40]
        data_props = onto.get_data_properties()[:40]
        schema_excerpt = "\n".join(
            [
                "Classes: " + ", ".join(classes),
                "Object properties: " + ", ".join(obj_props),
                "Data properties: " + ", ".join(data_props),
            ]
        )
    except Exception as exc:
        logger.warning("Schema excerpt failed: %s", exc)

    if include_documents and settings.get("semantic_enable_graph_rag", True):
        try:
            from services.document_ingestor import retrieve_grounded_document_sections

            graphrag = retrieve_grounded_document_sections(
                query=question,
                tenant_id=tenant_id,
                top_k_concepts=min(5, top_k),
                top_k_sections=5,
            )
            document_sections = graphrag.get("document_sections") or []
        except Exception as exc:
            logger.debug("GraphRAG semantic retrieval skipped: %s", exc)

    return {
        "concepts": concepts,
        "document_sections": document_sections,
        "schema_excerpt": schema_excerpt,
        "hybrid_meta": hybrid_meta,
        "retrieval_meta": retrieval_meta,
    }


def format_semantic_context(semantic: dict[str, Any], *, ontology_id: str = "hc-core") -> str:
    """Build ontology_context text from a semantic memory bundle."""
    concept_lines = []
    for item in (semantic.get("concepts") or [])[:8]:
        if isinstance(item, dict):
            name = item.get("name") or ""
            score = item.get("rerank_score") or item.get("score")
            src = item.get("source") or ""
            desc = item.get("description") or ""
            line = f"- {name}"
            if score is not None:
                line += f" (score={score}"
                if src:
                    line += f", src={src}"
                line += ")"
            if desc:
                line += f": {str(desc)[:160]}"
            concept_lines.append(line)

    doc_lines = []
    for sec in (semantic.get("document_sections") or [])[:5]:
        if isinstance(sec, dict):
            content = (sec.get("content") or "")[:200]
            concept = sec.get("concept_name") or sec.get("concept") or ""
            doc_lines.append(f"- [{concept}] {content}")

    parts = [
        f"Ontology: {ontology_id}",
        "Relevant concepts (semantic memory):",
        *(concept_lines or ["- (none retrieved)"]),
    ]
    if doc_lines:
        parts.extend(["", "Grounded document evidence:", *doc_lines])
    schema = semantic.get("schema_excerpt") or ""
    if schema:
        parts.extend(["", "Schema excerpt:", schema])
    return "\n".join(parts)
