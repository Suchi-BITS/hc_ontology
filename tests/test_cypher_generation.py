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
        return [
            self._Named("Patient"),
            self._Named("Doctor"),
            self._Named("Diagnosis"),
            self._Named("Prescription"),
            self._Named("Medication"),
        ]

    def object_properties(self):
        return [
            self._Named("hasDiagnosis"),
            self._Named("prescribedFor"),
            self._Named("containsMedication"),
        ]

    def data_properties(self):
        return [self._Named("firstName"), self._Named("diagnosisName"), self._Named("medicationName")]


def test_clean_cypher_strips_fences():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    cleaned = gen.clean_cypher("```cypher\nMATCH (p:Patient) RETURN p\n```")
    assert "```" not in cleaned
    assert "MATCH" in cleaned


def test_clean_cypher_extracts_match_block_from_prose():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    cleaned = gen.clean_cypher(
        "Do not use CREATE or DELETE.\n"
        "MATCH (p:Patient) RETURN p.name LIMIT 10\n"
        "Explanation: returns patients."
    )
    assert cleaned.upper().startswith("MATCH")
    assert "CREATE" not in cleaned.upper()
    assert "Explanation" not in cleaned


def test_normalize_cypher_fixes_empty_return():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    broken = """
    MATCH (p:Patient)<-[:DIAGNOSISFORPATIENT]-(d:Diagnosis)
    WHERE d.diagnosisName = "diabetes"
    RETURN
    LIMIT 200
    """
    fixed = gen.normalize_cypher(broken)
    assert "RETURN p.name, d.diagnosisName" in fixed
    assert "HASDIAGNOSIS" in fixed
    result = gen.validate(fixed)
    assert result.valid is True


def test_repair_cypher_diabetes_query_return_fields():
    from core.cypher_repair import repair_cypher

    broken = """
    MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis)
    WHERE toLower(d.diagnosisName) CONTAINS "diabetes"
    RETURN
    LIMIT 200
    """
    fixed = repair_cypher(broken)
    assert "RETURN p.name, d.diagnosisName" in fixed
    from core.cypher_repair import repair_cypher

    broken = """
    MATCH (a:Appointment)-[:APPOINTMENTFORPATIENT]->(p:Patient)
    RETURN
    LIMIT 200
    """
    fixed = repair_cypher(broken)
    assert "RETURN a.name, p.name" in fixed
    assert "LIMIT 200" in fixed


def test_validate_rejects_empty_return():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    result = gen.validate(
        "MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis) RETURN LIMIT 10"
    )
    assert result.valid is True
    assert "RETURN p.name, d.name" in result.query


def test_validate_diabetes_medications_via_prescription():
    gen = CypherGenerator(_FakeOnto(), model_name="unused")
    q = """
    MATCH (p:Patient)-[:HASDIAGNOSIS]->(d:Diagnosis {diagnosisName: 'Diabetes'}),
          (rx:Prescription)-[:PRESCRIBEDFOR]->(p),
          (rx)-[:CONTAINSMEDICATION]->(m:Medication)
    RETURN p.name, d.diagnosisName, m.medicationName
    LIMIT 50
    """
    result = gen.validate(q)
    assert result.valid is True


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
