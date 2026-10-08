"""Doctor SHACL shape tests against fixtures."""


def test_doctor_requires_specialty(validator):
    data = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    hc:DrNoSpec a hc:Doctor .
    """
    result = validator.validate_rdf_text(
        data,
        rdf_format="turtle",
        shape_files=["doctor_shapes.ttl"],
    )
    assert result.summary.conforms is False
    assert any(
        v.result_path
        and "hasSpecialty" in v.result_path
        and v.severity == "Violation"
        for v in result.violations
    )


def test_valid_doctor_fixture(validator, sample_instances_dir):
    result = validator.validate_data_file(
        sample_instances_dir / "valid_doctor.ttl",
        shape_files=["doctor_shapes.ttl"],
    )
    assert result.summary.conforms is True
    assert result.summary.violation_count == 0
