"""Bounded execution of externally submitted SPARQL.

The problem. rdflib runs a query inside one synchronous call. A query such as a four-way cartesian
COUNT(*) never returns, cannot be cancelled, and holds an API worker for as long as it runs.
`asyncio.wait_for` or a client-side timeout would only stop *waiting*; the work, and the CPU, would go on.

The design. Queries run in a small pool of worker processes (core/sparql_worker.py). The parent waits at most
SPARQL_QUERY_TIMEOUT_SECONDS for the answer. If it does not come, the parent KILLS the worker process, which
really stops the computation and frees its memory, starts a fresh worker for the next request, and raises
SparqlTimeout (a TimeoutError, which the API maps to 504 with a short message).

Trade-offs, stated plainly:
  + a hard bound: a runaway query is terminated, not abandoned
  + the parsed graph stays warm inside each worker, so normal queries are *faster* than the old
    parse-the-file-on-every-call behaviour
  - a worker process costs start-up time (about a second, once, plus once per timeout) and memory (one parsed graph each)
  - a killed query's partial work is lost, by design
  - workers are bounded (SPARQL_WORKERS); when all are busy a request waits, and if it waits as long as the limit
    it fails with SparqlBusy (503) instead of queueing without bound
  - this bounds TIME, not memory inside one query; result size is bounded separately by the injected LIMIT
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger("healthcare_ontology.query")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STARTUP_SECONDS = 60.0  # parsing the ontology at worker start; not counted against a query's own limit


class SparqlTimeout(TimeoutError):
    """The query ran longer than the configured limit and its worker was terminated."""


class SparqlBusy(RuntimeError):
    """Every worker stayed busy for the whole limit."""


class SparqlExecutionError(ValueError):
    """The query failed inside the engine (for example a syntax error). Carries a short, safe message."""


class _Worker:
    def __init__(self, dataset):
        self.dataset = dataset
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()

    # -- lifecycle ---------------------------------------------------------------------------------
    def _start(self) -> None:
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "core.sparql_worker", *[str(p) for p in self.dataset.paths]],
            cwd=PROJECT_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
        )
        threading.Thread(target=self._pump, args=(self.proc, self.lines), daemon=True).start()
        first = self._take(STARTUP_SECONDS)
        if first is None or not first.get("ready"):
            self.kill()
            raise SparqlExecutionError("the SPARQL worker did not start")

    @staticmethod
    def _pump(proc: subprocess.Popen, lines: queue.Queue) -> None:
        try:
            for line in proc.stdout:
                try:
                    lines.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            lines.put(None)  # EOF: the process ended

    def _take(self, seconds: float):
        try:
            return self.lines.get(timeout=seconds)
        except queue.Empty:
            return "timeout"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            for stream in (proc.stdin, proc.stdout):
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass

    # -- one query ----------------------------------------------------------------------------------
    def run(self, query: str, timeout: float) -> list[list[str]]:
        if not self.alive():
            self.kill()
            self._start()
        try:
            self.proc.stdin.write(json.dumps({"query": query}) + "\n")
            self.proc.stdin.flush()
        except OSError:
            self.kill()
            raise SparqlExecutionError("the SPARQL worker is unavailable") from None
        reply = self._take(timeout)
        if reply == "timeout":
            self.kill()  # the only thing that really stops a runaway query
            raise SparqlTimeout(f"SPARQL query exceeded the {timeout:g}-second limit and was terminated")
        if reply is None:
            self.kill()
            raise SparqlExecutionError("the SPARQL worker stopped unexpectedly")
        if "error" in reply:
            raise SparqlExecutionError(reply["error"])
        return reply["ok"]


class SparqlRunner:
    def __init__(self, dataset, workers: int = 2):
        self.dataset = dataset
        self._pool: queue.Queue[_Worker] = queue.Queue()
        self._all = [_Worker(dataset) for _ in range(workers)]
        for w in self._all:
            self._pool.put(w)

    def run(self, query: str, timeout: float) -> list[list[str]]:
        try:
            worker = self._pool.get(timeout=timeout)
        except queue.Empty:
            raise SparqlBusy(f"all SPARQL workers were busy for {timeout:g} seconds") from None
        try:
            return worker.run(query, timeout)
        except SparqlTimeout:
            logger.warning("SPARQL query terminated after %ss", timeout)
            raise
        finally:
            self._pool.put(worker)

    def worker_pids(self) -> list[int]:
        return [w.proc.pid for w in self._all if w.alive()]

    def close(self) -> None:
        for w in self._all:
            w.kill()


_runners: dict[tuple[str, int], SparqlRunner] = {}
_lock = threading.Lock()


def get_runner(source, workers: int) -> SparqlRunner:
    """source: a Dataset or a path to one RDF file. One runner (and its workers) per distinct dataset."""
    from core.dataset import as_dataset

    dataset = as_dataset(source)
    dataset = type(dataset)(dataset.schema.resolve(), dataset.data.resolve() if dataset.data else None)
    key = (tuple(str(p) for p in dataset.paths), workers)
    with _lock:
        if key not in _runners:
            _runners[key] = SparqlRunner(dataset, workers)
        return _runners[key]


def shutdown_all() -> None:
    with _lock:
        for runner in _runners.values():
            runner.close()
        _runners.clear()


import atexit  # noqa: E402

atexit.register(shutdown_all)
