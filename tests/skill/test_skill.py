"""Validate both Agent Skills, evaluation data, templates, and setup checks."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from skills_ref import read_properties, validate

from mcp_capability_router import __version__

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "mcp-capability-router-skills" / "skills"
SKILLS = sorted(path for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").is_file())
LINK = re.compile(r"\]\(([^)#<>\s]+)(?:#[^)]*)?\)")
# Every warning is an error, and so is a deprecation that the script itself triggers;
# the package is held to the same rule by the test suite.
WARNINGS = [
    "-W",
    "error",
    "-W",
    "ignore::DeprecationWarning",
    "-W",
    "error::DeprecationWarning:__main__",
]


def run(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executes this repository's own templates
        [sys.executable, *WARNINGS, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
        cwd=cwd,
    )


def test_both_skills_are_discoverable() -> None:
    assert [skill.name for skill in SKILLS] == [
        "mcp-capability-router",
        "mcp-capability-router-extend",
    ]
    config = json.loads((ROOT / "skills.sh.json").read_text(encoding="utf-8"))
    assert [(ROOT / path).resolve() for path in config["paths"]] == [SKILLS_ROOT.resolve()]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda path: path.name)
def test_skill_specification_and_all_links(skill: Path) -> None:
    properties = read_properties(skill)
    assert validate(skill) == []
    assert properties.name == skill.name
    assert properties.license == "Apache-2.0"
    assert properties.metadata["version"] == __version__
    assert properties.description.startswith("Use this skill when")
    assert "Do not use it" in properties.description
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert len(body.splitlines()) < 500
    for folder in ("references", "assets", "scripts"):
        for path in (skill / folder).glob("*"):
            if path.is_file():
                assert f"{folder}/{path.name}" in body
    for page in skill.rglob("*.md"):
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if "://" not in target:
                assert (page.parent / target).exists(), (page, target)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda path: path.name)
def test_evaluations_and_trigger_splits(skill: Path) -> None:
    data = json.loads((skill / "evals" / "evals.json").read_text(encoding="utf-8"))
    assert data["skill_name"] == skill.name
    assert len(data["evals"]) >= 3
    assert len({case["id"] for case in data["evals"]}) == len(data["evals"])
    for case in data["evals"]:
        assert case["prompt"]
        assert case["expected_output"]
        assert len(case["assertions"]) >= 3
        for name in case.get("files", []):
            assert (skill / "evals" / name).is_file()
    triggers = json.loads((skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8"))
    assert triggers["skill_name"] == skill.name
    queries = triggers["queries"]
    assert len(queries) >= 16
    assert len({query["query"] for query in queries}) == len(queries)
    assert 0.5 <= sum(q["split"] == "train" for q in queries) / len(queries) <= 0.7
    assert 0.4 <= sum(q["should_trigger"] for q in queries) / len(queries) <= 0.6
    for split in ("train", "validation"):
        assert {q["should_trigger"] for q in queries if q["split"] == split} == {True, False}


def test_positive_triggers_do_not_overlap() -> None:
    positives = []
    for skill in SKILLS:
        data = json.loads((skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8"))
        positives.append({q["query"].lower() for q in data["queries"] if q["should_trigger"]})
    assert not positives[0] & positives[1]


def test_setup_check_and_integration_template() -> None:
    core = SKILLS_ROOT / "mcp-capability-router"
    completed = run(str(core / "scripts" / "verify_setup.py"), "--json")
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["ok"]
    assert report["version"] == __version__
    completed = run(str(core / "assets" / "integration_template.py"))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "rejected:" in completed.stdout


def test_registry_template_contract(tmp_path: Path) -> None:
    assets = SKILLS_ROOT / "mcp-capability-router-extend" / "assets"
    completed = run(
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={tmp_path}",
        f"--rootdir={assets}",
        str(assets),
        cwd=assets,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "passed" in completed.stdout
