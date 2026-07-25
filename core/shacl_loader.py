"""Load and merge SHACL shape graphs from the shapes/ directory."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rdflib import Graph

from core.shacl_exceptions import ShaclShapeLoadError

logger = logging.getLogger("healthcare_ontology.shacl")

DEFAULT_SHAPES_DIR = Path(__file__).resolve().parent.parent / "shapes"

# Always pulled in when loading a domain subset so sh:node composition works.
_COMMON_RELATIVE = (
    "common/prefixes.ttl",
    "common/person_shapes.ttl",
)


def load_all_shapes(shapes_dir: str | Path | None = None) -> Graph:
    """
    Walk `shapes/` recursively and merge every `.ttl` into one rdflib.Graph.

    This is the single entry point for the full shapes package (manifest + modules).
    """
    return ShaclLoader(shapes_dir).load_all()


class ShaclLoader:
    """Loads Turtle SHACL shape files into an rdflib Graph."""

    def __init__(self, shapes_dir: str | Path | None = None):
        self.shapes_dir = Path(shapes_dir) if shapes_dir else DEFAULT_SHAPES_DIR

    def discover_shape_files(self) -> list[Path]:
        """All `.ttl` files under shapes/, sorted (manifest first, then common/, then rest)."""
        if not self.shapes_dir.is_dir():
            return []

        files = list(self.shapes_dir.rglob("*.ttl"))

        def sort_key(p: Path) -> tuple:
            rel = p.relative_to(self.shapes_dir).as_posix()
            if rel == "shapes_manifest.ttl":
                return (0, rel)
            if rel.startswith("common/"):
                return (1, rel)
            return (2, rel)

        return sorted(files, key=sort_key)

    def list_shape_files(self) -> list[str]:
        """Relative posix paths of discovered shape modules."""
        return [
            p.relative_to(self.shapes_dir).as_posix()
            for p in self.discover_shape_files()
        ]

    def resolve_path(self, name: str) -> Path:
        """Resolve a shape file by relative path or basename under shapes_dir."""
        direct = self.shapes_dir / name
        if direct.is_file():
            return direct
        matches = [
            p
            for p in self.discover_shape_files()
            if p.name == name or p.relative_to(self.shapes_dir).as_posix() == name
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ShaclShapeLoadError(f"Ambiguous shape file name: {name}")
        raise ShaclShapeLoadError(f"Shape file not found: {name} (under {self.shapes_dir})")

    def load_file(self, filename: str) -> Graph:
        path = self.resolve_path(filename)
        graph = Graph()
        try:
            graph.parse(str(path), format="turtle")
        except Exception as exc:
            raise ShaclShapeLoadError(f"Failed to parse shape file {path}: {exc}") from exc
        return graph

    def load_all(self) -> Graph:
        """Merge every `.ttl` under shapes/ into one graph."""
        if not self.shapes_dir.is_dir():
            raise ShaclShapeLoadError(f"Shapes directory not found: {self.shapes_dir}")

        paths = self.discover_shape_files()
        if not paths:
            raise ShaclShapeLoadError(f"No .ttl shape files found under {self.shapes_dir}")

        merged = Graph()
        loaded: list[str] = []
        for path in paths:
            try:
                merged.parse(str(path), format="turtle")
            except Exception as exc:
                raise ShaclShapeLoadError(f"Failed to parse {path}: {exc}") from exc
            loaded.append(path.relative_to(self.shapes_dir).as_posix())

        logger.info("Loaded %d SHACL shape file(s): %s", len(loaded), ", ".join(loaded))
        return merged

    def load(self, filenames: Iterable[str] | None = None) -> Graph:
        """
        Load shapes. With no filenames, loads the full package via load_all().
        With a subset, also includes common/ so composed node shapes resolve.
        """
        if filenames is None:
            return self.load_all()

        if not self.shapes_dir.is_dir():
            raise ShaclShapeLoadError(f"Shapes directory not found: {self.shapes_dir}")

        requested = list(filenames)
        # Ensure PersonShape / prefixes are present for domain subsets
        names: list[str] = []
        for common in _COMMON_RELATIVE:
            if (self.shapes_dir / common).is_file() and common not in requested:
                names.append(common)
        for name in requested:
            if name not in names:
                names.append(name)

        merged = Graph()
        loaded: list[str] = []
        for name in names:
            path = self.resolve_path(name)
            try:
                merged.parse(str(path), format="turtle")
            except ShaclShapeLoadError:
                raise
            except Exception as exc:
                raise ShaclShapeLoadError(f"Failed to parse {path}: {exc}") from exc
            loaded.append(path.relative_to(self.shapes_dir).as_posix())

        if not loaded:
            raise ShaclShapeLoadError(
                f"No SHACL shape files loaded from {self.shapes_dir}"
            )

        logger.info("Loaded %d SHACL shape file(s): %s", len(loaded), ", ".join(loaded))
        return merged

    def health(self) -> dict:
        files = self.list_shape_files()
        manifest = self.shapes_dir / "shapes_manifest.ttl"
        return {
            "shapes_dir": str(self.shapes_dir),
            "exists": self.shapes_dir.is_dir(),
            "shape_files": files,
            "count": len(files),
            "manifest_present": manifest.is_file(),
            "ready": self.shapes_dir.is_dir() and len(files) > 0,
        }


@lru_cache
def get_default_shapes_graph() -> Graph:
    """Cached merged shapes graph for repeated validations."""
    return load_all_shapes()
