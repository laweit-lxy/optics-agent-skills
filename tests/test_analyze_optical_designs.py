"""Regression tests for skills/analyze-optical-designs (pinned Chromatix and Prysm)."""
from __future__ import annotations

import pytest

from conftest import REPO, read_report, run_entry

pytest.importorskip("prysm", reason="install skills/analyze-optical-designs/requirements.txt")

ENTRY = REPO / "skills" / "analyze-optical-designs" / "scripts" / "optics_regression.py"


@pytest.fixture(scope="module")
def self_test(tmp_path_factory):
    output = tmp_path_factory.mktemp("analyze").resolve() / "self-test.json"
    result = run_entry(ENTRY, "--self-test", "--output", output)
    return result, read_report(output)


def test_self_test_passes(self_test):
    result, report = self_test
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["passed"] is True


def test_pins_and_freeze_match(self_test):
    _, report = self_test
    assert report["provenance"]["pins_match"]
    freeze = report["freeze"]
    assert not (freeze["missing"] or freeze["extra"] or freeze["mismatched"]), freeze


@pytest.mark.parametrize("check", ["chromatix", "prysm", "chromatix_gradient", "prysm_analytic_mtf"])
def test_numerical_check(self_test, check):
    _, report = self_test
    assert report[check]["passed"], report[check]
