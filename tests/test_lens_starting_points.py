"""First-order qualification of the catalog with the pinned skill entries."""
from __future__ import annotations

import os
from importlib.util import find_spec

import pytest

from conftest import REPO, read_report, run_entry, sha256

LIBRARY = REPO / "lens-starting-points"
CATALOG = read_report(LIBRARY / "catalog.json")
ENTRIES = tuple(CATALOG["entries"])
ENTRY_IDS = tuple(entry["id"] for entry in ENTRIES)
OPTILAND = REPO / "skills/design-optical-systems/scripts/optiland_regression.py"
RAYOPTICS = REPO / "skills/cross-check-optical-designs/scripts/rayoptics_crosscheck.py"


def _source(entry):
    return (LIBRARY / entry["zmx"]).resolve()


def _require_engine(package, skill):
    if find_spec(package) is not None:
        return
    message = f"run with the {skill} environment: {package} is missing"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(message)
    pytest.skip(message)


def _assert_metrics(entry, efl, f_number):
    ref = entry["reference"]
    assert efl == pytest.approx(ref["efl_mm"], abs=ref["efl_abs_tolerance_mm"], rel=0)
    assert f_number == pytest.approx(ref["paraxial_f_number"], abs=ref["f_number_abs_tolerance"], rel=0)


def _assert_unchanged(source_report, entry):
    assert source_report["sha256_before"] == source_report["sha256_after"] == entry["sha256"]
    assert sha256(_source(entry)) == entry["sha256"]


def test_catalog():
    assert CATALOG["schema_version"] == 1
    assert ENTRY_IDS and len(set(ENTRY_IDS)) == len(ENTRIES)
    assert len({_source(entry) for entry in ENTRIES}) == len(ENTRIES)
    for entry in ENTRIES:
        source = _source(entry)
        assert source.is_relative_to(REPO) and source.suffix == ".zmx"
        assert sha256(source) == entry["sha256"]
        assert entry["primary_wavelength_um"] in entry["wavelengths_um"]
        ref = entry["reference"]
        if "fixture" in ref:
            original = read_report(LIBRARY / ref["fixture"])
            assert original["source_sha256"] == entry["sha256"]
            first_order = original["first_order"]
            assert ref["efl_mm"] == first_order["effective_focal_length_mm"]["value"]
            assert ref["paraxial_f_number"] == first_order["paraxial_f_number"]["value"]


@pytest.mark.parametrize("entry", ENTRIES, ids=ENTRY_IDS)
def test_optiland(entry, out_dir):
    _require_engine("optiland", "design-optical-systems")
    output = out_dir / "optiland.json"
    result = run_entry(OPTILAND, "--input-zmx", _source(entry), "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(output)
    assert report["status"] == "PASS", report["failed_checks"]
    analysis = report["analysis"]
    _assert_unchanged(analysis["source"], entry)
    assert analysis["surface"]["surface_count"] == entry["surface_count"]
    assert analysis["surface"]["stop_surfaces"] == [entry["stop_surface"]]
    metrics = analysis["metrics"]
    assert metrics["wavefront"]["wavelength_um"] == pytest.approx(entry["primary_wavelength_um"])
    _assert_metrics(entry, metrics["effective_focal_length_mm"], metrics["f_number"])


@pytest.mark.parametrize("entry", ENTRIES, ids=ENTRY_IDS)
def test_rayoptics(entry, out_dir):
    _require_engine("rayoptics", "cross-check-optical-designs")
    output = out_dir / "rayoptics.json"
    result = run_entry(RAYOPTICS, "--input-zmx", _source(entry), "--output", output)
    assert result.returncode == 0, result.stdout + result.stderr
    report = read_report(output)
    assert report["status"] == "INSPECTED", report["failed_checks"]
    _assert_unchanged(report["source"], entry)
    model = report["model"]
    assert model["sequential"]["surface_count"] == entry["surface_count"]
    assert model["sequential"]["stop_surface"] == entry["stop_surface"]
    spec = model["optical_spec"]
    assert [field["y"] for field in spec["fields"]] == pytest.approx(entry["field_angles_y_deg"])
    wavelengths = spec["wavelengths"]
    assert [wave["wavelength_nm"] / 1000 for wave in wavelengths] == pytest.approx(entry["wavelengths_um"])
    assert [wave["wavelength_nm"] / 1000 for wave in wavelengths if wave["primary"]] == pytest.approx(
        [entry["primary_wavelength_um"]]
    )
    _assert_metrics(entry, model["first_order"]["efl"], model["first_order"]["fno"])
