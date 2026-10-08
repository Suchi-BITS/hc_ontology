"""Validate the ontology and data end to end. Needs no Neo4j and no API keys.

    python scripts/validate.py              # model, shapes, projection plan
    python scripts/validate.py --reasoner   # also run the OWL reasoner (needs Java)

Checks, in order (exit code 1 if any fails):
  0. the CSV sample data satisfies the data contract (references, codes, dates, classifications)
  1. the schema and the sample data parse (separately and together); the schema holds no instances
  2. each committed artifact is exactly what its generator produces
  3. schema + sample data conform to the SHACL shapes (no Violations)
  4. the RDF projects cleanly into the property-graph model
  5. (optional) the OWL reasoner finds the ontology consistent
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reasoner", action="store_true", help="also run the OWL reasoner (needs Java)")
    args = parser.parse_args()
    failures: list[str] = []

    from rdflib import OWL, RDF, Graph
    from rdflib.compare import isomorphic

    step(0, "Sample-data contract (data/source/*.csv)")
    from services import sample_data

    problems = sample_data.check_dataset(sample_data.load_dataset(), sample_data.load_drug_reference(),
                                         source_dir=sample_data.SOURCE_DIR)
    print(f"    {sum(len(rows) for rows in sample_data.load_dataset().values())} rows, {len(problems)} problem(s)")
    for p in problems:
        print(f"    {p}")
    if problems:
        failures.append("sample data breaks the data contract")

    step(1, "Parse the schema and the sample data (separately, then together)")
    from core.dataset import Dataset

    dataset = Dataset.default()
    schema_graph = Graph()
    data_graph = Graph()
    try:
        from core.dataset import parse_into

        parse_into(schema_graph, dataset.schema)
        if dataset.data is not None:
            parse_into(data_graph, dataset.data)
    except Exception as exc:  # noqa: BLE001
        print(f"    {exc}")
        raise SystemExit(1)
    graph = dataset.graph()
    classes = len(list(schema_graph.subjects(RDF.type, OWL.Class)))
    schema_individuals = set(schema_graph.subjects(RDF.type, OWL.NamedIndividual))
    data_individuals = set(data_graph.subjects(RDF.type, OWL.NamedIndividual))
    print(f"    schema      {dataset.schema.name}: {len(schema_graph)} triples, {classes} classes, "
          f"{len(schema_individuals)} vocabulary individuals")
    if dataset.data is not None:
        print(f"    sample data {dataset.data.name}: {len(data_graph)} triples, {len(data_individuals)} individuals")
    print(f"    combined: {len(graph)} triples")
    if classes < 50:
        failures.append("the schema is smaller than expected")
    if dataset.data is not None and len(data_individuals) < 50:
        failures.append("the sample data is smaller than expected")
    # schema purity is checked on the committed file, without importing the generator (keeps this step cheap)
    pure_problems = [f"{str(i).split('#')[-1]} is an instance in the schema" for i in schema_individuals
                     if not {str(x).split("#")[-1] for x in schema_graph.objects(i, RDF.type)}
                     & {"Specialty", "AdministrativeGender", "EncounterType", "MedicationCategory", "ConceptScheme"}]
    for line in pure_problems:
        print(f"    {line}")
    if pure_problems:
        failures.append("the schema contains instance data")

    step(2, "Committed artifacts equal what the generators produce")
    with tempfile.TemporaryDirectory() as tmp:
        schema_out, data_out = Path(tmp) / "schema.ttl", Path(tmp) / "data.ttl"
        checks = [("schema", "generate_hc_ontology.py", schema_out, [], schema_graph)]
        if dataset.data is not None:  # SAMPLE_DATA_FILE empty: the platform runs on the schema alone
            checks.append(("sample data", "generate_sample_data.py", data_out, ["--schema", str(dataset.schema)], data_graph))
        else:
            print("    sample data: not configured (SAMPLE_DATA_FILE is empty); schema only")
        for label, script, out, extra, committed in checks:
            done = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--output", str(out), *extra],
                                  capture_output=True, text=True, cwd=ROOT)
            if done.returncode != 0:
                print(done.stderr[-800:])
                failures.append(f"the {label} generator failed")
            elif isomorphic(Graph().parse(out, format="turtle"), committed):
                print(f"    {label}: identical (as RDF graphs)")
            else:
                failures.append(f"the committed {label} differs from the generator output; run scripts/{script}")
                print(f"    {label}: DIFFERENT")

    step(3, "SHACL validation")
    from core.config import get_settings
    from core.dependencies import get_shacl_validator

    result = get_shacl_validator().validate_ontology()
    s = result.summary
    print(f"    conforms={s.conforms}  violations={s.violation_count}  warnings={s.warning_count}  infos={s.info_count}")
    for v in result.violations:
        print(f"    {v.severity:9} {v.focus_node.rsplit('#', 1)[-1]}: {v.message}")
    if not s.conforms or s.violation_count:
        failures.append("SHACL violations")

    step(4, "Project to the property-graph model (no database)")
    from services.graph_projection import ProjectionError, build_projection

    try:
        projection = build_projection(graph)
        info = projection.summary()
        print(f"    {info['nodes']} nodes, {info['classes']} classes, {info['relationships']} relationships")
        print(f"    fingerprint {info['fingerprint'][:16]}...")
    except ProjectionError as exc:
        print(f"    {exc}")
        failures.append("projection")

    if args.reasoner:
        step(5, "OWL reasoner (HermiT)")
        if shutil.which("java") is None:
            print("    SKIPPED: Java not found (install a JRE to run the reasoner)")
        else:
            sys.path.insert(0, str(ROOT))
            from tests.reasoning import reason

            _world, _onto = reason(graph)
            bad = list(_world.inconsistent_classes())
            print(f"    consistent; unsatisfiable classes: {len(bad)}")
            if bad:
                failures.append("the ontology has unsatisfiable classes")

    print()
    if failures:
        print("VALIDATION FAILED: " + "; ".join(failures))
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
