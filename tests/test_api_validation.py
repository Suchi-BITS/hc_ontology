"""API-level SHACL validation tests."""


def test_validation_health(client):
    r = client.get("/validation/health")
    assert r.status_code == 200
    body = r.json()
    assert body["shapes"]["ready"] is True
    assert body["pyshacl_installed"] is True
    assert body["shapes"]["manifest_present"] is True


def test_validate_ontology_endpoint(client):
    r = client.post("/validate/ontology", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["conforms"] is True
    assert body["summary"]["violation_count"] == 0
    assert body["summary"]["data_source"].endswith("sample_data.ttl")
    assert [v for v in body["violations"] if v["severity"] == "Violation"] == []


def test_validate_inline_patient(client):
    ttl = """
    @prefix hc: <http://example.org/healthcare-hospital.owl#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    hc:PatientX a hc:Patient ;
        hc:firstName "X"^^xsd:string ;
        hc:dateOfBirth "2001-01-01"^^xsd:string ;
        hc:bloodGroup "B-"^^xsd:string .
    """  # lastName is missing and dateOfBirth is a string, not xsd:date
    r = client.post(
        "/validate",
        json={
            "data": ttl,
            "format": "turtle",
            "shape_files": ["patient_shapes.ttl"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["conforms"] is False
    messages = {v["message"] for v in body["violations"] if v["severity"] == "Violation"}
    assert "Patient must have a lastName." in messages
    assert any("xsd:date" in m for m in messages)


def test_validation_report_after_run(client):
    posted = client.post("/validate/ontology", json={}).json()
    r = client.get("/validation/report")
    assert r.status_code == 200
    assert r.json()["summary"]["validated_at"] == posted["summary"]["validated_at"]
    assert r.json()["summary"]["conforms"] is True


def test_validation_report_html(client):
    bad = "@prefix hc: <http://example.org/healthcare-hospital.owl#> . hc:P a hc:Patient ."
    client.post("/validate", json={"data": bad, "format": "turtle", "shape_files": ["patient_shapes.ttl"]})
    r = client.get("/validation/report", params={"format": "html"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "SHACL" in r.text
    assert "Patient must have a dateOfBirth." in r.text  # the report shows the actual finding


def test_openapi_has_shacl_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/validate" in paths
    assert "/validate/ontology" in paths
    assert "/validate/file" in paths
    assert "/validation/health" in paths
    assert "/validation/report" in paths
