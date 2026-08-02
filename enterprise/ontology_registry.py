"""Multi-ontology registry with knowledge versioning."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import get_settings


@dataclass
class OntologyVersion:
    version: str
    created_at: str
    checksum: str
    owl_path: str
    changelog: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class OntologyRecord:
    ontology_id: str
    name: str
    tenant_ids: list[str]
    active_version: str
    versions: list[OntologyVersion] = field(default_factory=list)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _checksum(path: Path) -> str:
    if not path.is_file():
        return "missing"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


class OntologyRegistry:
    """Catalog of tenant-scoped ontologies and immutable version snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        settings = get_settings()
        root = Path(settings["project_root"])
        owl = Path(settings["owl_file"])
        if not owl.is_absolute():
            owl = root / owl
        now = datetime.now(timezone.utc).isoformat()
        checksum = _checksum(owl)
        v1 = OntologyVersion(
            version="1.0.0",
            created_at=now,
            checksum=checksum,
            owl_path=str(owl),
            changelog="Initial healthcare core ontology",
            labels=["stable", "default"],
        )
        self._ontologies: dict[str, OntologyRecord] = {
            "hc-core": OntologyRecord(
                ontology_id="hc-core",
                name="Healthcare Core",
                tenant_ids=["default", "clinic-a", "research"],
                active_version="1.0.0",
                versions=[v1],
                description="Primary hospital OWL ontology",
            ),
            "hc-clinical-ext": OntologyRecord(
                ontology_id="hc-clinical-ext",
                name="Clinical Extensions",
                tenant_ids=["clinic-a"],
                active_version="1.0.0",
                versions=[
                    OntologyVersion(
                        version="1.0.0",
                        created_at=now,
                        checksum=checksum,
                        owl_path=str(owl),
                        changelog="Alias of core until extension OWL is provided",
                        labels=["preview"],
                    )
                ],
                description="Clinic-specific extensions (shares core file until split)",
            ),
            "hc-research": OntologyRecord(
                ontology_id="hc-research",
                name="Research Ontology",
                tenant_ids=["research"],
                active_version="1.0.0",
                versions=[
                    OntologyVersion(
                        version="1.0.0",
                        created_at=now,
                        checksum=checksum,
                        owl_path=str(owl),
                        changelog="Research tenant view",
                        labels=["research"],
                    )
                ],
                description="Research-scoped ontology view",
            ),
        }
        self._store_path = root / "data" / "ontology_registry.json"

    def list(self, tenant_id: str | None = None) -> list[OntologyRecord]:
        with self._lock:
            items = list(self._ontologies.values())
        if tenant_id:
            items = [o for o in items if tenant_id in o.tenant_ids]
        return items

    def get(self, ontology_id: str) -> OntologyRecord | None:
        with self._lock:
            return self._ontologies.get(ontology_id)

    def resolve_owl_path(
        self, ontology_id: str, version: str | None = None
    ) -> tuple[str, OntologyVersion]:
        rec = self.get(ontology_id)
        if not rec:
            raise KeyError(f"Unknown ontology: {ontology_id}")
        ver = version or rec.active_version
        for v in rec.versions:
            if v.version == ver:
                return v.owl_path, v
        raise KeyError(f"Unknown version {ver} for ontology {ontology_id}")

    def publish_version(
        self,
        ontology_id: str,
        version: str,
        owl_path: str,
        changelog: str = "",
        labels: list[str] | None = None,
        activate: bool = False,
    ) -> OntologyRecord:
        path = Path(owl_path)
        now = datetime.now(timezone.utc).isoformat()
        ov = OntologyVersion(
            version=version,
            created_at=now,
            checksum=_checksum(path),
            owl_path=str(path.resolve()),
            changelog=changelog,
            labels=labels or [],
        )
        with self._lock:
            rec = self._ontologies.get(ontology_id)
            if not rec:
                raise KeyError(f"Unknown ontology: {ontology_id}")
            if any(v.version == version for v in rec.versions):
                raise ValueError(f"Version {version} already exists")
            rec.versions.append(ov)
            if activate:
                rec.active_version = version
            self._persist_unlocked()
            return rec

    def set_active(self, ontology_id: str, version: str) -> OntologyRecord:
        with self._lock:
            rec = self._ontologies.get(ontology_id)
            if not rec:
                raise KeyError(ontology_id)
            if not any(v.version == version for v in rec.versions):
                raise KeyError(version)
            rec.active_version = version
            self._persist_unlocked()
            return rec

    def _persist_unlocked(self) -> None:
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {k: v.to_dict() for k, v in self._ontologies.items()}
            self._store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass


ontology_registry = OntologyRegistry()
