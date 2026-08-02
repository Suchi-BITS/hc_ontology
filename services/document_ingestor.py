from __future__ import annotations

import datetime as _dt
import io
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

from neo4j import GraphDatabase

from core.config import get_settings
from core.dependencies import get_embedding_service


_WHITESPACE_RE = re.compile(r"\s+")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    # Keep it simple/deterministic: collapse whitespace.
    return _WHITESPACE_RE.sub(" ", (text or "").strip())


def chunk_text(text: str, *, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
    """Character-based chunking with overlap.

    Note: For richer chunking by paragraphs/pages, add a dedicated splitter later.
    """
    text = _normalize_text(text)
    if not text:
        return []

    chunk_size = int(chunk_size)
    overlap = int(overlap)
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")

    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        end = min(len(text), start + chunk_size)
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(text):
            break
    return chunks


def _read_text_upload(*, content: bytes, filename: str) -> str:
    """Extract plain text from an uploaded file.

    Current strategy:
    - text-like files: utf-8/latin-1 decode
    - .docx: XML-from-zip extraction (no external deps)
    - .pdf: best-effort naive extraction for text-based PDFs
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix in (".docx",):
        return _extract_docx_text(content)
    if suffix in (".pdf",):
        return _extract_pdf_text_naive(content)

    # Best-effort decode for text-like uploads.
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1", errors="replace")


def _extract_docx_text(file_bytes: bytes) -> str:
    """Extract text from a .docx by reading `word/document.xml`."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            xml_bytes = z.read("word/document.xml")
    except Exception as exc:
        raise ValueError(f"Failed to read .docx payload: {exc}") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        raise ValueError(f"Failed to parse .docx XML: {exc}") from exc

    # Collect runs of `w:t` (text nodes). This is a common approach and avoids
    # needing python-docx.
    out: list[str] = []
    for el in root.iter():
        tag = el.tag
        if tag.endswith("}t"):
            if el.text:
                out.append(el.text)
        elif tag.endswith("}br"):
            out.append("\n")
    return "".join(out)


def _pdf_unescape_text(s: str) -> str:
    # Very small subset of PDF string escape rules.
    # Replace escaped newline etc; keep it conservative.
    return (
        s.replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
    )


def _extract_pdf_text_naive(file_bytes: bytes, *, max_streams: int = 200) -> str:
    """Best-effort PDF text extraction (no external PDF libs).

    This targets simple, text-based PDFs that store content streams with
    FlateDecode compression and use `Tj` / `TJ` operators with literal strings.

    If extraction yields little/no text, return an empty string so the caller
    can fail fast.
    """
    data = file_bytes

    # Find candidate FlateDecode streams and decompress them.
    # This is intentionally heuristic.
    try:
        import zlib
    except Exception:
        return ""

    # Regex: grab any stream blocks preceded by /FlateDecode somewhere nearby.
    # We keep the overall runtime bounded by limiting matches.
    stream_pattern = re.compile(
        rb"/FlateDecode.*?stream\r?\n(?P<stream>.*?)\r?\nendstream",
        re.DOTALL,
    )
    matches = list(stream_pattern.finditer(data))
    if not matches:
        # Try to extract uncompressed literal strings anyway (rare but cheap).
        raw = data.decode("latin-1", errors="ignore")
        return _pdf_unescape_text(" ".join(re.findall(r"\(([^)]*)\)\s*Tj", raw)))

    text_out: list[str] = []
    for m_idx, m in enumerate(matches[:max_streams]):
        stream_bytes = m.group("stream")
        # Decompress with zlib; PDFs sometimes omit/alter zlib headers,
        # so try both standard and raw inflate.
        decompressed: bytes
        try:
            decompressed = zlib.decompress(stream_bytes)
        except Exception:
            try:
                decompressed = zlib.decompress(stream_bytes, wbits=-zlib.MAX_WBITS)
            except Exception:
                continue

        decoded = decompressed.decode("latin-1", errors="ignore")

        # Tj: (text) Tj
        text_out.extend(
            _pdf_unescape_text(s)
            for s in re.findall(r"\(([^)]*)\)\s*Tj", decoded)
        )

        # TJ: [ (a) ... (b) ] TJ (we extract all literal-string chunks)
        text_out.extend(
            _pdf_unescape_text(s)
            for s in re.findall(r"\(([^)]*)\)", decoded)
        )

    joined = " ".join(t.strip() for t in text_out if t and t.strip())
    return joined.strip()


def _neo4j_driver():
    settings = get_settings()
    return GraphDatabase.driver(
        settings["neo4j_uri"],
        auth=(settings["neo4j_username"], settings["neo4j_password"]),
    )


@dataclass(frozen=True)
class UploadGroundingConfig:
    chunk_size: int = 1500
    chunk_overlap: int = 200
    max_chunks: int = 20
    grounding_top_k: int = 3
    grounding_min_score: float = 0.0


def ingest_uploaded_text_document(
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    title: str,
    tenant_id: str,
    ontology_id: str,
    ontology_version: str,
    source_type: str,
    config: UploadGroundingConfig,
) -> dict[str, Any]:
    """Ingest a healthcare document as grounded sections in Neo4j.

    GraphRAG grounding approach:
    1) split document into sections (chunks)
    2) embed each chunk and retrieve relevant ontology concepts
    3) create `(:DocumentSection)-[:GROUNDS_IN {confidence_score}]->(:OntologyConcept)`
    """
    if not file_bytes:
        raise ValueError("Uploaded document is empty.")

    text = _read_text_upload(content=file_bytes, filename=filename)
    chunks = chunk_text(
        text,
        chunk_size=config.chunk_size,
        overlap=config.chunk_overlap,
    )
    if not chunks:
        raise ValueError("Could not extract any text from uploaded content.")

    chunks = chunks[: max(1, int(config.max_chunks))]

    embedding_service = get_embedding_service()
    # Creates the vector index if missing. If the ontology embeddings haven't
    # been synced yet, GraphRAG grounding will return empty matches.
    if hasattr(embedding_service, "ensure_vector_index"):
        embedding_service.ensure_vector_index()

    driver = _neo4j_driver()
    database = get_settings()["neo4j_database"]

    document_id = str(uuid.uuid4())
    created_at = _now_iso()

    section_ids: list[str] = []

    # Create Document + DocumentSections first, then add grounding edges.
    with driver.session(database=database) as session:
        session.run(
            """
            MERGE (d:Document {document_id: $document_id})
            SET d.title = $title,
                d.filename = $filename,
                d.content_type = $content_type,
                d.tenant_id = $tenant_id,
                d.ontology_id = $ontology_id,
                d.ontology_version = $ontology_version,
                d.source_type = $source_type,
                d.created_at = $created_at
            """,
            document_id=document_id,
            title=title or filename,
            filename=filename,
            content_type=content_type or "",
            tenant_id=tenant_id,
            ontology_id=ontology_id,
            ontology_version=ontology_version,
            source_type=source_type,
            created_at=created_at,
        )

        for idx, chunk in enumerate(chunks):
            section_id = str(uuid.uuid4())
            section_ids.append(section_id)
            session.run(
                """
                MERGE (s:DocumentSection {section_id: $section_id})
                SET s.document_id = $document_id,
                    s.tenant_id = $tenant_id,
                    s.ontology_id = $ontology_id,
                    s.ontology_version = $ontology_version,
                    s.chunk_index = $chunk_index,
                    s.content = $content
                """,
                section_id=section_id,
                document_id=document_id,
                tenant_id=tenant_id,
                ontology_id=ontology_id,
                ontology_version=ontology_version,
                chunk_index=idx,
                content=chunk,
            )
            session.run(
                """
                MATCH (d:Document {document_id: $document_id})
                MATCH (s:DocumentSection {section_id: $section_id})
                MERGE (d)-[:HAS_SECTION]->(s)
                """,
                document_id=document_id,
                section_id=section_id,
            )

        # Ground each chunk to top ontology concepts.
        grounded_edges = 0
        for idx, (section_id, chunk_text_value) in enumerate(zip(section_ids, chunks)):
            try:
                groundings = embedding_service.similarity_search_detailed(
                    chunk_text_value,
                    top_k=config.grounding_top_k,
                )
            except Exception:
                groundings = []

            # Filter by min-score to reduce noisy edges.
            filtered = [
                g for g in (groundings or [])
                if g.get("score") is not None and float(g["score"]) >= float(config.grounding_min_score)
            ]

            if not filtered:
                continue

            session.run(
                """
                UNWIND $groundings AS g
                MERGE (c:OntologyConcept {name: g.name})
                WITH c, g
                MATCH (s:DocumentSection {section_id: $section_id})
                MERGE (s)-[r:GROUNDS_IN]->(c)
                SET r.confidence_score = g.score,
                    r.grounding_method = $method
                """,
                section_id=section_id,
                method="embedding",
                groundings=[
                    {"name": str(g["name"]), "score": float(g.get("score") or 0.0)}
                    for g in filtered
                ],
            )
            grounded_edges += len(filtered)

    return {
        "status": "success",
        "document_id": document_id,
        "title": title or filename,
        "filename": filename,
        "tenant_id": tenant_id,
        "ontology_id": ontology_id,
        "ontology_version": ontology_version,
        "chunks_created": len(chunks),
        "grounding_edges_created": grounded_edges,
        "source_type": source_type,
        "created_at": created_at,
    }


def retrieve_grounded_document_sections(
    *,
    query: str,
    tenant_id: str,
    top_k_concepts: int = 5,
    top_k_sections: int = 10,
) -> dict[str, Any]:
    """Retrieve grounded document sections for a question (ontology-only grounding)."""
    embedding_service = get_embedding_service()
    embedding_service.ensure_vector_index()

    ontology_hits = embedding_service.similarity_search_detailed(
        query,
        top_k=top_k_concepts,
    )
    concept_names = [h["name"] for h in ontology_hits if h.get("name")]
    if not concept_names:
        return {
            "query": query,
            "tenant_id": tenant_id,
            "ontology_hits": [],
            "document_sections": [],
        }

    driver = _neo4j_driver()
    database = get_settings()["neo4j_database"]
    with driver.session(database=database) as session:
        rows = session.run(
            """
            MATCH (ds:DocumentSection {tenant_id: $tenant_id})-[r:GROUNDS_IN]->(c:OntologyConcept)
            WHERE c.name IN $concept_names
            RETURN
                ds.section_id AS section_id,
                ds.document_id AS document_id,
                ds.chunk_index AS chunk_index,
                ds.content AS content,
                c.name AS concept_name,
                r.confidence_score AS grounding_score
            ORDER BY grounding_score DESC
            LIMIT $limit
            """,
            tenant_id=tenant_id,
            concept_names=concept_names,
            limit=int(top_k_sections),
        )
        sections = [dict(r) for r in rows]

    return {
        "query": query,
        "tenant_id": tenant_id,
        "ontology_hits": ontology_hits,
        "document_sections": sections,
    }

