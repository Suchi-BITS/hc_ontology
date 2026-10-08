"""Tests for lexical memory helpers."""

from enterprise.lexical_memory import (
    expand_tokens,
    overlap_score,
    split_name_tokens,
    tokens_for_learning,
)


def test_split_name_tokens_patient_john():
    tokens = split_name_tokens("PatientJohn")
    assert "patient" in tokens
    assert "john" in tokens


def test_expand_tokens_diabetic_maps_to_diabetes():
    expanded = expand_tokens(["diabetic"])
    assert "diabetes" in expanded


def test_overlap_score_john_doe_question():
    score = overlap_score(
        ["john", "doe", "diagnosis"],
        "PatientJohn DiagnosisHypertension john doe",
    )
    assert score >= 0.6


def test_tokens_for_learning_includes_concepts_and_query():
    keys = tokens_for_learning(
        "Show diabetic patients",
        validated_query="MATCH (p:Patient)-[:HASDIAGNOSIS]->(d) RETURN p",
        concept_names=["Patient", "DiagnosisDiabetes"],
    )
    assert "patient" in keys
    assert "diabetes" in keys or "diabetic" in keys
    assert "match" in keys
