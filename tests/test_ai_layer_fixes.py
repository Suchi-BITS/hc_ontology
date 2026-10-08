"""Regression tests for defects found by the live verification of the optional AI layer
(docs/AI_LAYER_LIVE_VERIFICATION.md). None of these needs OpenAI or Neo4j; the live behaviour is in
tests/test_ai_live.py (opt-in).

1. NL -> SPARQL: the prompt named properties without direction and did not say which were never stored, so the model
   wrote valid queries that matched nothing.
2. Embeddings: `store_embedding` referenced an undefined name, so every concept failed to store (after being embedded
   and paid for).
3. Abstention: an out-of-domain ontology-only question was `completed` at confidence 0.76.
"""

from __future__ import annotations

import pytest
import rdflib

from core.config import ConfigurationError, get_settings
from core.dataset import Dataset
from enterprise.abstention import decide_abstention


# ---- 1. the SPARQL prompt tells the model what exists and which way it points ------------------------------------

@pytest.fixture(scope="module")
def generator():
    from core.dependencies import get_sparql_generator

    return get_sparql_generator()


def test_every_property_in_the_prompt_carries_its_direction(generator):
    text = generator.build_prompt("Which patients have diabetes?")
    for line in ("hasDiagnosis (Patient -> Diagnosis)", "prescribedFor (Prescription -> Patient)",
                 "participatesIn (Practitioner -> Encounter)", "diagnosisName (Diagnosis -> str)"):
        assert line in text, line


def test_inverse_only_properties_are_listed_as_not_stored_with_the_property_to_use(generator):
    text = generator.build_prompt("x")
    assert "diagnosisForPatient [use hasDiagnosis]" in text
    assert "allergyForPatient [use hasAllergy]" in text
    assert "NOT STORED in the data" in text


def test_the_prompt_never_marks_a_property_the_data_really_uses_as_not_stored(generator):
    """The list comes from the ontology's own comments; this checks it against the actual sample data."""
    flagged = {line.split(" ")[0] for line in generator.inferred_properties_text().splitlines()}
    data = rdflib.Graph().parse(Dataset.default().data, format="turtle")
    stored = {str(p).split("#")[-1] for p in data.predicates()}
    assert flagged and flagged.isdisjoint(stored), sorted(flagged & stored)


def test_the_prompt_tells_the_model_to_query_the_most_specific_class(generator):
    assert "most\nspecific class" in generator.build_prompt("x") or "most specific class" in " ".join(generator.build_prompt("x").split())


# ---- 2. embeddings are actually stored ---------------------------------------------------------------------------------

class _Session:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.log.append((cypher, params))


class _Driver:
    def __init__(self):
        self.log = []

    def session(self, database=None):
        return _Session(self.log)


def test_processing_a_concept_stores_its_vector_and_its_text():
    from services.embedding_service import EmbeddingService

    service = object.__new__(EmbeddingService)            # no Neo4j, no OpenAI: only the code path that was broken
    service.driver, service.database = _Driver(), "neo4j"
    service.generate_embedding = lambda text: [0.1, 0.2, 0.3]
    result = service.process_document({"node_name": "Metformin", "text": "Metformin: an antidiabetic medication."})
    assert result == {"node": "Metformin", "dimensions": 3, "status": "stored"}
    (cypher, params), = service.driver.log
    assert "MERGE" in cypher and "n.embedding = $embedding" in cypher
    assert params == {"name": "Metformin", "embedding": [0.1, 0.2, 0.3], "description": "Metformin: an antidiabetic medication."}


def test_a_long_description_is_truncated_not_rejected():
    from services.embedding_service import EmbeddingService

    service = object.__new__(EmbeddingService)
    service.driver, service.database = _Driver(), "neo4j"
    service.store_embedding("X", [0.0], "y" * 9000)
    assert len(service.driver.log[0][1]["description"]) == 4000


# ---- 3. abstention on ontology-only questions --------------------------------------------------------------------------

def ontology_only(top_score, concepts=True):
    return {
        "query_type": "ontology_only", "validation_ok": True,
        "retrieved_concepts": [{"name": "RadiationTherapy", "rerank_score": top_score, "channel_score": top_score}] if concepts else [],
        "results": [{"name": "RadiationTherapy"}] * 8,        # the execution step "succeeds" with the retrieved concepts
    }


def test_irrelevant_retrieval_is_not_evidence():
    """The live case: best concept match 0.25 for 'What is the capital of France?'; confidence was 0.76 and it was 'completed'."""
    decision = decide_abstention(ontology_only(0.25))
    assert decision["refused"] is True and decision["refusal_reason"] == "no_evidence"


def test_relevant_retrieval_is_still_answered():
    decision = decide_abstention(ontology_only(0.62))
    assert decision["refused"] is False and decision["refusal_reason"] is None


def test_the_floor_is_exactly_the_configured_value(configure):
    configure(AGENT_ONTOLOGY_MIN_RELEVANCE="0.5")
    assert decide_abstention(ontology_only(0.45))["refused"] is True
    assert decide_abstention(ontology_only(0.55))["refused"] is False
    configure(AGENT_ONTOLOGY_MIN_RELEVANCE="0.0")
    assert decide_abstention(ontology_only(0.01))["refused"] is False


def test_no_concepts_at_all_still_refuses():
    decision = decide_abstention(ontology_only(0.9, concepts=False))
    assert decision["refused"] is True and decision["refusal_reason"] == "missing_provenance"   # no concepts means no provenance path


def test_query_backed_answers_are_unaffected_by_the_ontology_floor():
    state = {"query_type": "cypher", "validated_query": "MATCH (p:Patient) RETURN p", "validation_ok": True,
             "results": [{"p": "x"}] * 5, "retrieved_concepts": [{"name": "Patient", "rerank_score": 0.2}]}
    assert decide_abstention(state)["refused"] is False


@pytest.mark.parametrize("bad", ["abc", "-0.1", "1.5", "nan"])
def test_an_invalid_relevance_floor_fails_by_name(configure, bad):
    configure(AGENT_ONTOLOGY_MIN_RELEVANCE=bad)
    with pytest.raises(ConfigurationError, match="AGENT_ONTOLOGY_MIN_RELEVANCE must be a number between 0 and 1"):
        get_settings()


def test_the_default_floor_is_documented():
    from pathlib import Path

    assert "AGENT_ONTOLOGY_MIN_RELEVANCE" in (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    assert get_settings()["agent_ontology_min_relevance"] == 0.30


# ---- 4. error details never echo a key ------------------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-proj-ab************************wxyz.'}}",
    "bad header X-API-Key: hck_AbCdEfGhIjKlMnOpQrStUv",  # pragma: allowlist secret
    "tracing failed for lsv2_pt_0123456789abcdef0123456789abcdef_01234567",  # pragma: allowlist secret
])
def test_error_details_returned_to_clients_contain_no_key_shaped_text(message):
    from core.errors import map_query_exception

    detail = str(map_query_exception(RuntimeError(message)).detail)
    for fragment in ("sk-proj", "hck_AbCd", "lsv2_pt_0123"):
        assert fragment not in detail
    assert "[redacted-key]" in detail


def test_ordinary_error_text_is_left_alone():
    from core.errors import map_query_exception

    assert "task-queue" in str(map_query_exception(RuntimeError("the task-queue was full")).detail)   # 'sk-' inside a word is not a key
