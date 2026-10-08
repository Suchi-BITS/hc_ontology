"""Test doubles: a recording Neo4j driver and a stub SHACL validator."""


class FakeResult:
    def single(self):
        return {"c": 0}


class FakeTx:
    def __init__(self, log):
        self.log = log

    def run(self, cypher, **params):
        self.log.append(("tx", cypher, params))
        return FakeResult()


class FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self.log.append(("auto", cypher, params))
        return FakeResult()

    def execute_write(self, fn):
        return fn(FakeTx(self.log))


class FakeDriver:
    def __init__(self):
        self.log = []
        self.sessions = 0

    def session(self, database=None):
        self.sessions += 1
        return FakeSession(self.log)

    def close(self):
        pass


class Validator:
    """Stands in for the SHACL validator."""

    def __init__(self, violations=()):
        self._violations = violations
        self.calls = 0

    def validate_graph(self, graph, **kwargs):
        self.calls += 1
        violations = [type("V", (), {"severity": "Violation", "focus_node": f"{'http://x#'}{n}", "message": m})
                      for n, m in self._violations]
        return type("R", (), {"violations": violations})
