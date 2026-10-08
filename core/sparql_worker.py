"""The child-process side of bounded SPARQL execution. Run as:  python -m core.sparql_worker <schema-file> [<data-file>]

Why a separate process: rdflib evaluates a query synchronously inside one Python call that cannot be
interrupted from outside (no cancellation hook, and a thread cannot be killed). The only mechanism that
really stops a runaway query is to stop the process that runs it. The parent (core/sparql_exec.py) does
exactly that when the time limit passes; this process holds the parsed graph so ordinary queries do not
pay a parse each time.

Protocol, one JSON object per line:  {"query": "..."}  ->  {"ok": [[...], ...]} | {"error": "...", "kind": "..."}
Nothing else may be written to stdout. Imports are kept to the standard library and rdflib so start-up is cheap.
"""

from __future__ import annotations

import json
import os
import sys


def load_graph(dataset):
    # The union of schema and sample data. String literals are normalised once, at load: Owlready2 writes every
    # string as "x"^^xsd:string, which rdflib will not match against a query's plain "x" (see Dataset.graph).
    return dataset.graph(normalise_strings=True)


def main(paths: list[str]) -> int:
    from pathlib import Path

    from core.dataset import Dataset

    dataset = Dataset(Path(paths[0]), Path(paths[1]) if len(paths) > 1 else None)
    graph, stamp = None, None
    out = sys.stdout
    out.write(json.dumps({"ready": True}) + "\n")
    out.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            query = json.loads(line)["query"]
            current = dataset.stamp()
            if graph is None or current != stamp:  # a dataset file was regenerated: reload
                graph, stamp = load_graph(dataset), current
            rows = [[str(x) for x in row] for row in graph.query(query)]
            reply = {"ok": rows}
        except Exception as exc:  # noqa: BLE001 - reported to the parent as text, never as a stack trace
            reply = {"error": str(exc)[:300], "kind": type(exc).__name__}
        out.write(json.dumps(reply) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
