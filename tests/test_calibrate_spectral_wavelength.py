"""Regression tests for skills/calibrate-spectral-wavelength (pinned RASCAL)."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import REPO, read_report, sha256

pytest.importorskip("rascal", reason="install skills/calibrate-spectral-wavelength/requirements.txt")

SKILL = REPO / "skills" / "calibrate-spectral-wavelength"
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
    result = run(SKILL / "scripts" / "calibrate.py", "--input", EXAMPLE, "--output-dir", target)
    assert result.returncode == 2
    assert not any(target.iterdir())


def test_example_calibrates_and_leaves_input_unchanged(out_dir):
    before = sha256(EXAMPLE)
    result = run(SKILL / "scripts" / "calibrate.py", "--input", EXAMPLE, "--output-dir", out_dir / "example")
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(out_dir / "example" / "report.json")
    assert report["status"] == "PASS", report.get("error")
    assert sha256(EXAMPLE) == before == report["input"]["sha256_after"]
    coefficients = report["polynomial"]["coefficients"]
    assert [c["unit"] for c in coefficients] == ["nm", "nm/pixel^1", "nm/pixel^2"]
    assert abs(coefficients[0]["value"] - 400.0) < 0.1
    assert abs(coefficients[1]["value"] - 0.2256) < 1e-3


def test_regression_suite(out_dir):
    result = run(SKILL / "tests" / "regression.py", "--output-dir", out_dir / "regression")
    summary = read_report(out_dir / "regression" / "regression.json")
    failed = [name for name, ok in summary["checks"].items() if not ok]
    assert summary["status"] == "PASS" and result.returncode == 0, (failed, summary["runs"])
    assert summary["additional_seeds"] == {"successes": 3, "total": 3}
