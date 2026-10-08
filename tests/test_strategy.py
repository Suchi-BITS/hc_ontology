"""The test suite polices itself."""

from pathlib import Path

import pytest

from tests.levels import DESCRIPTIONS, LEVELS, levels_for

TESTS = Path(__file__).resolve().parent


def test_every_test_module_belongs_to_a_pyramid_level():
    modules = {p.stem for p in TESTS.glob("test_*.py")} - {"test_strategy"}
    unclassified = sorted(m for m in modules if not levels_for(m))
    assert unclassified == [], f"add these to tests/levels.py: {unclassified}"


def test_the_level_table_names_no_module_that_does_not_exist():
    modules = {p.stem for p in TESTS.glob("test_*.py")}
    named = {m for mods in LEVELS.values() for m in mods}
    assert sorted(named - modules) == []


def test_every_level_is_registered_as_a_marker(pytestconfig):
    registered = {line.split(":")[0].strip() for line in pytestconfig.getini("markers")}
    assert set(DESCRIPTIONS) <= registered


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_every_level_has_tests(level):
    assert LEVELS[level], level


def test_the_documented_levels_match_the_code():
    doc = (TESTS.parent / "docs" / "testing-strategy.md").read_text(encoding="utf-8")
    for level in LEVELS:
        assert f"`{level}`" in doc, f"docs/testing-strategy.md does not describe level {level}"


def test_unfilled_env_example_placeholders_count_as_unset(configure):
    from core.config import get_settings

    configure(OPENAI_API_KEY="<your-openai-api-key>", NEO4J_PASSWORD="<your-neo4j-password>")
    s = get_settings()
    assert s["openai_api_key"] == "" and s["neo4j_password"] == ""
    configure(OPENAI_API_KEY="sk-real", NEO4J_PASSWORD="real-pass")
    s = get_settings()
    assert s["openai_api_key"] == "sk-real" and s["neo4j_password"] == "real-pass"
