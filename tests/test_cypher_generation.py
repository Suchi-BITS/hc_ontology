"""Cypher generator validation helpers (no live Ollama required)."""

from core.cypher_validator import CypherQueryValidator
from services.cypher_generator import CypherGenerator


class _FakeOnto:
    class _Named:
        def __init__(self, name):
            self.name = name

    def __init__(self):
        self.onto = self

    def classes(self):
        return [self._Named("Patient"), self._Named("Doctor")]

    def object_properties(self):
        return [self._Named("hasDiagnosis")]

    def data_properties(self):
        return [self._Named("firstName")]


def test_clean_cypher_strips_fences():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    cleaned = gen.clean_cypher("```cypher\nMATCH (p:Patient) RETURN p\n```")
    assert "```" not in cleaned
    assert "MATCH" in cleaned


def test_validate_read_query():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    result = gen.validate("MATCH (p:Patient) RETURN p.name LIMIT 10")
    assert result.valid is True


def test_validate_rejects_write():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    result = gen.validate(
        "MATCH (p:Patient) CREATE (x:Patient {name:'X'}) RETURN p"
    )
    assert result.valid is False
    assert result.stage == "safety"
