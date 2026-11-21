"""Regression tests for skills/cross-check-optical-designs against OpticStudio references."""
from __future__ import annotations

import json
import math

import pytest

from conftest import REPO, SAMPLES, read_report, run_entry, sample_reference, sample_zmx, sha256, unit_copy

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


def _unit_reports(out_dir, reference=None, **copy_options):
    reports = {}
    for unit in ("MM", "IN", "INCH"):
        source = unit_copy(sample_zmx("hubble"), out_dir / f"hubble-{unit}.zmx", unit, **copy_options)
        output = out_dir / f"hubble-{unit}.json"
        args = ["--reference-json", reference] if reference else []
        result = run_entry(ENTRY, "--input-zmx", source, *args, "--output", output)
        assert result.returncode == 0, result.stdout + result.stderr
        reports[unit] = read_report(output)
    return reports


def _assert_same_mm_outputs(reports):
    base = reports["MM"]["model"]
    for unit in ("IN", "INCH"):
        model = reports[unit]["model"]
        assert model["system_units"] == "in"
        for name, value in base["first_order"].items():
            assert model["first_order"][name] == pytest.approx(value, rel=1e-9, abs=1e-9), name
        for a, b in zip(base["sequential"]["interfaces"], model["sequential"]["interfaces"], strict=True):
            for key in ("curvature_per_mm", "radius_mm", "thickness_after_mm"):
                expected = a[key] if a[key] is None or isinstance(a[key], str) else pytest.approx(a[key], rel=1e-9)
                assert b[key] == expected, key
        assert model["optical_spec"]["field_units"] == base["optical_spec"]["field_units"]
        assert model["optical_spec"]["maximum_field"] == pytest.approx(base["optical_spec"]["maximum_field"])
        for a, b in zip(base["optical_spec"]["fields"], model["optical_spec"]["fields"], strict=True):
            assert (b["x"], b["y"]) == pytest.approx((a["x"], a["y"]), rel=1e-9, abs=1e-12)


def test_inch_prescription_reports_millimetres(out_dir):
    reports = _unit_reports(out_dir, sample_reference("hubble"))
    assert reports["MM"]["model"]["system_units"] == "mm"
    for unit, report in reports.items():
        assert report["status"] == "PASS", (unit, report["failed_checks"])
        assert report["model"]["first_order"]["efl"] == pytest.approx(EXPECTED_EFL_MM["hubble"], rel=1e-9)
        assert report["comparison"]["metrics"]["effective_focal_length_mm"]["passed"]
    _assert_same_mm_outputs(reports)
    # import_info stays as RayOptics returned it, in the file's system units.
    stand_in = {unit: report["model"]["import_info"][0]["inf object"] for unit, report in reports.items()}
    assert stand_in["MM"] == pytest.approx(reports["MM"]["model"]["sequential"]["interfaces"][0]["thickness_after_mm"])
    assert stand_in["IN"] * 25.4 == pytest.approx(stand_in["MM"], rel=1e-9)


def test_finite_object_and_height_field_in_inches(out_dir):
    reports = _unit_reports(out_dir, object_distance_mm=1e10, height_field=True)
    for unit, report in reports.items():
        assert report["status"] == "INSPECTED", (unit, report["failed_checks"])
        assert report["software"]["rayoptics_source_manifest"]["matches_pin"]
        model = report["model"]
        assert "inf object" not in model["import_info"][0]
        assert model["sequential"]["interfaces"][0]["thickness_after_mm"] == pytest.approx(1e10, rel=1e-12)
        assert model["optical_spec"]["field_units"] == "mm"
        assert model["optical_spec"]["maximum_field"] == pytest.approx(0.15, rel=1e-12)
    _assert_same_mm_outputs(reports)


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
