"""Regression tests for skills/build-optomechanical-parts (pinned CadQuery)."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import REPO, read_report, sha256

pytest.importorskip("cadquery", reason="install skills/build-optomechanical-parts/requirements.txt")

SKILL = REPO / "skills" / "build-optomechanical-parts"
EXAMPLE = SKILL / "examples" / "input.json"


def run(script, *args):
    """Run a skill script as its SKILL.md documents it: isolated, UTF-8 mode."""
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-I", str(script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", timeout=1800,
    )


def test_runtime_gate(out_dir):
    result = run(SKILL / "scripts" / "contract.py", "--output-dir", out_dir / "env")
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(out_dir / "env" / "environment.json")
    assert report["status"] == "PASS", report["checks"]
    assert report["mismatched_distributions"] == {}


def test_existing_output_directory_is_refused(out_dir):
    target = out_dir / "taken"
    target.mkdir()
    result = run(SKILL / "scripts" / "build.py", "--input", EXAMPLE, "--output-dir", target)
    assert result.returncode == 2
    assert not any(target.iterdir())


def test_example_builds_parts_and_assembly(out_dir):
    before = sha256(EXAMPLE)
    target = out_dir / "example"
    result = run(SKILL / "scripts" / "build.py", "--input", EXAMPLE, "--output-dir", target)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(target / "report.json")
    assert report["status"] == "PASS", report.get("error")
    assert sha256(EXAMPLE) == before == report["input"]["sha256_after"]
    assert {part["name"] for part in report["parts"]} == {"mount", "tube"}
    for name in ("mount.step", "mount.stl", "tube.step", "tube.stl", "assembly.step"):
        assert (target / name).stat().st_size > 0, name


def test_regression_suite(out_dir):
    result = run(SKILL / "tests" / "regression.py", "--output-dir", out_dir / "regression")
    summary = read_report(out_dir / "regression" / "regression.json")
    failed = [name for name, ok in summary["checks"].items() if not ok]
    assert summary["status"] == "PASS" and result.returncode == 0, failed
