"""Regression tests for skills/cross-check-optical-designs against OpticStudio references."""
from __future__ import annotations

import json
import math

import pytest

from conftest import REPO, SAMPLES, read_report, run_entry, sample_reference, sample_zmx, sha256

pytest.importorskip("rayoptics", reason="install skills/cross-check-optical-designs/requirements.txt")

ENTRY = REPO / "skills" / "cross-check-optical-designs" / "scripts" / "rayoptics_crosscheck.py"

# Values recorded in references/runtime-lock.md; OpticStudio references live in tests/data.
EXPECTED_EFL_MM = {
    "cooke": 50.00039433779174,
    "double-gauss": 100.0037478708372,
    "hubble": 57600.080998403595,
}
EXPECTED_GLASS_CATALOG = {"cooke": ("F2", "Hikari"), "double-gauss": ("F5", "Schott")}


@pytest.mark.parametrize("name", SAMPLES)
def test_matches_opticstudio_reference(name, out_dir):
    source = sample_zmx(name)
    before = sha256(source)
    output = out_dir / f"{name}.json"
    result = run_entry(ENTRY, "--input-zmx", source, "--reference-json", sample_reference(name),
                       "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(output)
    assert report["status"] == "PASS", report["failed_checks"]
    assert report["software"]["rayoptics_source_manifest"]["matches_pin"]
    assert sha256(source) == before == report["source"]["sha256_after"]
    efl = report["model"]["first_order"]["efl"]
    assert math.isclose(efl, EXPECTED_EFL_MM[name], rel_tol=1e-9)
    assert report["comparison"]["relative_tolerance"] == 1e-4


@pytest.mark.parametrize("name", sorted(EXPECTED_GLASS_CATALOG))
def test_named_glass_resolves_in_declared_catalog(name, out_dir):
    output = out_dir / f"{name}.json"
    result = run_entry(ENTRY, "--input-zmx", sample_zmx(name), "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(output)
    assert report["status"] == "INSPECTED"
    glass, catalog = EXPECTED_GLASS_CATALOG[name]
    resolved = {(entry["declared_name"], entry["resolved_catalog"].casefold())
                for entry in report["model"]["catalog_resolution"]}
    assert (glass, catalog.casefold()) in resolved


def test_perturbed_reference_is_mismatch(out_dir):
    reference = json.loads(sample_reference("cooke").read_text(encoding="utf-8"))
    reference["first_order"]["effective_focal_length_mm"]["value"] *= 1.001
    perturbed = out_dir / "perturbed-reference.json"
    perturbed.write_text(json.dumps(reference), encoding="utf-8")
    output = out_dir / "mismatch.json"
    result = run_entry(ENTRY, "--input-zmx", sample_zmx("cooke"), "--reference-json", perturbed,
                       "--output", output)
    assert result.returncode == 1
    report = read_report(output)
    assert report["status"] == "MISMATCH"
    assert report["failed_checks"] == ["reference_first_order_match"]


def test_refuses_existing_output(out_dir):
    output = out_dir / "existing.json"
    output.write_text("{}", encoding="utf-8")
    result = run_entry(ENTRY, "--input-zmx", sample_zmx("cooke"), "--output", output)
    assert result.returncode == 2
    assert output.read_text(encoding="utf-8") == "{}"


def test_rejects_url_input(out_dir):
    result = run_entry(ENTRY, "--input-zmx", "https://example.com/lens.zmx",
                       "--output", out_dir / "url.json")
    assert result.returncode == 2
