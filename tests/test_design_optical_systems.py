"""Regression tests for skills/design-optical-systems (pinned Optiland 0.6.3)."""
from __future__ import annotations

import pytest

from conftest import REPO, read_report, run_entry, sample_zmx, sha256

pytest.importorskip("optiland", reason="install skills/design-optical-systems/requirements.txt")

ENTRY = REPO / "skills" / "design-optical-systems" / "scripts" / "optiland_regression.py"

# Known upstream findings kept visible but non-blocking (see references/runtime-lock.md).
KNOWN_NONBLOCKING = 2


@pytest.fixture(scope="module")
def self_test(tmp_path_factory):
    output = tmp_path_factory.mktemp("self-test").resolve() / "self-test.json"
    result = run_entry(ENTRY, "--self-test", "--output", output)
    return result, read_report(output)


def test_self_test_passes(self_test):
    result, report = self_test
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "PASS", report["failed_checks"]
    assert report["software"]["optiland_installed_code_manifest"]["matches_pin"]


def test_known_findings_stay_visible(self_test):
    _, report = self_test
    assert len(report["nonblocking_findings"]) == KNOWN_NONBLOCKING, report["nonblocking_findings"]


@pytest.mark.parametrize("name", ["cooke", "hubble"])
def test_analyzes_sample_zmx_read_only(name, out_dir):
    source = sample_zmx(name)
    before = sha256(source)
    output = out_dir / f"{name}.json"
    result = run_entry(ENTRY, "--input-zmx", source, "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(output)
    assert report["status"] == "PASS", report["failed_checks"]
    assert sha256(source) == before


def test_refuses_existing_output(out_dir):
    output = out_dir / "existing.json"
    output.write_text("{}", encoding="utf-8")
    result = run_entry(ENTRY, "--input-zmx", sample_zmx("cooke"), "--output", output)
    assert result.returncode == 2
    assert output.read_text(encoding="utf-8") == "{}"
