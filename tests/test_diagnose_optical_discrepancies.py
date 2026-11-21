"""Probes and the end-to-end diagnosis on the bundled samples.

Needs both engine environments (design-optical-systems and
cross-check-optical-designs), found as in optics_agent_skills.engines.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys

import pytest

from conftest import REPO, SAMPLES, read_report, sample_reference, sample_zmx, sha256, unit_copy

from optics_agent_skills import engines

DIAGNOSE = REPO / "skills" / "diagnose-optical-discrepancies" / "scripts" / "diagnose.py"


def _available() -> bool:
    try:
        engines.interpreter("design")
        engines.interpreter("crosscheck")
    except engines.EngineError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _available(), reason="needs both engine environments")

# Qualified outcomes: (status, experiment-confirmed causes).
EXPECTED = {
    "cooke": ("EXPLAINED", {"material_catalog", "ray_aiming", "pupil_coordinates"}),
    "double-gauss": ("EXPLAINED", {"ray_aiming", "pupil_coordinates"}),
    "hubble": ("AGREE", set()),
}
COOKE_EFL_HIKARI_MM = 50.00039433779174


@pytest.fixture(scope="module")
def cooke_probes(tmp_path_factory):
    out = tmp_path_factory.mktemp("probes")
    zmx = sample_zmx("cooke")
    before = sha256(zmx)
    probes = {
        "optiland": engines.probe("design", zmx, out / "optiland.json"),
        "optiland_hikari": engines.probe("design", zmx, out / "optiland-hikari.json",
                                         {"3": {"name": "F2", "catalog": "hikari"}}),
        "rayoptics": engines.probe("crosscheck", zmx, out / "rayoptics.json"),
    }
    assert sha256(zmx) == before
    return probes


def test_probes_record_the_catalog_each_engine_resolved(cooke_probes):
    for probe in cooke_probes.values():
        assert probe["schema"] == "optics-probe/1"
        assert probe["source"]["sha256_before"] == probe["source"]["sha256_after"]
        assert len(probe["surfaces"]) == 8 and probe["stop_index"] == 4
    assert cooke_probes["optiland"]["surfaces"][3]["material"]["catalog"].casefold() == "schott"
    assert cooke_probes["rayoptics"]["surfaces"][3]["material"]["catalog"].casefold() == "hikari"


def test_catalog_override_reproduces_rayoptics_efl(cooke_probes):
    assert cooke_probes["optiland_hikari"]["first_order"]["efl_mm"] == pytest.approx(COOKE_EFL_HIKARI_MM,
                                                                                     rel=1e-12)
    assert cooke_probes["rayoptics"]["first_order"]["efl_mm"] == pytest.approx(COOKE_EFL_HIKARI_MM, rel=1e-12)
    assert cooke_probes["optiland"]["first_order"]["efl_mm"] == pytest.approx(49.999783071431914, rel=1e-12)


@pytest.mark.parametrize("options", [{}, {"object_distance_mm": 1e10, "height_field": True}],
                         ids=["infinite-angle", "finite-height"])
def test_rayoptics_probe_reports_millimetres(options, out_dir):
    probes = {}
    for unit in ("MM", "IN", "INCH"):
        zmx = unit_copy(sample_zmx("hubble"), out_dir / f"hubble-{unit}.zmx", unit, **options)
        probes[unit] = engines.probe("crosscheck", zmx, out_dir / f"probe-{unit}.json")
    base = probes["MM"]
    assert base["first_order"]["efl_mm"] == pytest.approx(57600.080998403595, rel=1e-9)
    if options:
        assert base["surfaces"][0]["thickness_mm"] == pytest.approx(1e10, rel=1e-12)
        assert base["fields"]["max"] == pytest.approx(0.15, rel=1e-12)
    # The ~3.3e15 mm infinity stand-in loses precision when the tracer
    # subtracts large object-space coordinates. Both x86-64 CI platforms
    # observed a 2.48e-9 mm difference in the off-axis +x ray. Allow a
    # 1e-8 mm absolute floor there, still 10,000x below the diagnosis gate.
    ray_atol_mm = 1e-9 if options else 1e-8
    for unit in ("IN", "INCH"):
        probe = probes[unit]
        assert probe["first_order"] == pytest.approx(base["first_order"], rel=1e-9)
        assert probe["fields"]["max"] == pytest.approx(base["fields"]["max"], rel=1e-9)
        assert probe["fields"]["normalized"] == base["fields"]["normalized"]
        for a, b in zip(base["surfaces"], probe["surfaces"], strict=True):
            for key in ("radius_mm", "thickness_mm"):
                assert b[key] == (None if a[key] is None else pytest.approx(a[key], rel=1e-9)), key
        for a, b in zip(base["rays"], probe["rays"], strict=True):
            assert (b["x_mm"], b["y_mm"]) == pytest.approx((a["x_mm"], a["y_mm"]), rel=1e-9, abs=ray_atol_mm)


@pytest.mark.parametrize("name", SAMPLES)
def test_diagnosis_matches_qualified_outcome(name, out_dir):
    zmx = sample_zmx(name)
    before = sha256(zmx)
    result = subprocess.run([sys.executable, "-I", str(DIAGNOSE), "--input-zmx", str(zmx),
                             "--output-dir", str(out_dir / name), "--reference-json", str(sample_reference(name))],
                            capture_output=True, text=True, encoding="utf-8", timeout=1800)
    status, confirmed = EXPECTED[name]
    assert result.returncode == (0 if status in {"AGREE", "EXPLAINED"} else 1), result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == status
    report = read_report(out_dir / name / "diagnosis.json")
    assert sha256(zmx) == before
    assert report["schema"] == "optics-diagnosis/1" and report["status"] == status
    assert {c["category"] for c in report["causes"]} == confirmed
    assert all(c["confirmed_by"] for c in report["causes"])
    assert report["unresolved"] == []
    table = report["surface_comparison"]
    assert table["aligned_by_index"] and table["delta_order"] == ["optiland", "rayoptics"]
    assert len(table["rows"]) == {"cooke": 8, "double-gauss": 13, "hubble": 5}[name]
    if name == "cooke":
        glass = table["rows"][3]
        assert glass["optiland"]["glass_after"]["catalog"].casefold() == "schott"
        assert glass["rayoptics"]["glass_after"]["catalog"].casefold() == "hikari"
        assert glass["glass_matches"] is False
        assert abs(glass["delta"]["refractive_indices_after"][1]) == pytest.approx(4.6e-6, rel=0.12)
        swap = next(e for e in report["experiments"] if e["name"] == "material_catalog_swap")
        assert swap["kept"] and swap["efl_mm_after"] == pytest.approx(COOKE_EFL_HIKARI_MM, rel=1e-12)
        assert report["reference"]["rayoptics"]["agrees"] and not report["reference"]["optiland"]["agrees"]
    if name == "hubble":
        assert report["reference"]["optiland"]["agrees"] and report["reference"]["rayoptics"]["agrees"]
        return
    steps = {e["name"]: e for e in report["experiments"]}
    assert steps["vignetting"]["status"] == "RAN" and not steps["vignetting"]["kept"]
    assert steps["pupil_coordinates"]["kept"] and steps["pupil_coordinates"]["removed"] == 6
    assert steps["pupil_coordinates"]["result"]["rays"] == []
    reports = [read_report(out_dir / name / f"probe-{stage}.json") for stage in (
        "rayoptics", "optiland-ray-aiming", "optiland-vignetting", "optiland-pupil-coordinates")]
    max_before, max_after, count = 0.0, 0.0, 0
    for ref, aimed, vig, matched in zip(*(p["rays"] for p in reports), strict=True):
        if matched["target_stop_xy_mm"] is None:
            continue
        count += 1
        assert aimed["effective_pupil"] == vig["effective_pupil"] == matched["effective_pupil"] == ref["effective_pupil"]
        assert _xy(aimed) == pytest.approx(_xy(vig), abs=1e-12, rel=0)
        assert matched["target_stop_xy_mm"] == ref["stop_xy_mm"]
        assert math.dist(matched["stop_xy_mm"], ref["stop_xy_mm"]) <= 1e-6
        max_before = max(max_before, math.dist(_xy(aimed), _xy(ref)))
        max_after = max(max_after, math.dist(_xy(matched), _xy(ref)))
    assert count == 6
    assert max_before == pytest.approx({"cooke": 0.024685, "double-gauss": 0.001588}[name], rel=1e-3)
    assert max_after < 1e-5  # comfortably inside the 1e-4 mm diagnosis gate


def _xy(ray):
    return ray["x_mm"], ray["y_mm"]


def test_asymmetric_vignetting_replaces_only_the_effective_pupil(out_dir):
    zmx = out_dir / "asymmetric-vignetting.zmx"
    lines = sample_zmx("cooke").read_text(encoding="utf-8").splitlines()
    replacements = {"VCYN": "VCYN 0 0 0.15", "VDYN": "VDYN 0 0 0.07"}
    zmx.write_text("\n".join(replacements.get(line.split()[0], line) if line.split() else line
                             for line in lines) + "\n", encoding="utf-8")
    before = sha256(zmx)
    folder = out_dir / "diagnosis"
    report = engines.diagnose(zmx, folder)
    assert sha256(zmx) == before
    steps = {e["name"]: e for e in report["experiments"]}
    assert steps["vignetting"]["status"] == "RAN"
    assert steps["vignetting"]["settings"]["ray_aiming"] == "iterative"
    baseline = read_report(folder / "probe-optiland-ray-aiming.json")
    trial = read_report(folder / "probe-optiland-vignetting.json")
    assert baseline["first_order"] == trial["first_order"]
    probed = [r for r in baseline["rays"] if r["field_index"] == 2 and abs(r["pupil"][1]) == 1]
    changed = [r for r in trial["rays"] if r["field_index"] == 2 and abs(r["pupil"][1]) == 1]
    assert len(probed) == len(changed) == 2
    for native, aligned in zip(probed, changed, strict=True):
        sign = native["pupil"][1]
        assert native["effective_pupil"] == pytest.approx([0.0, sign * 0.85])
        assert aligned["effective_pupil"] == pytest.approx([0.0, sign * 0.85 + 0.07])
        assert math.dist(native["stop_xy_mm"], aligned["stop_xy_mm"]) > 0.1
        assert aligned["target_stop_xy_mm"] is None


def test_refuses_non_empty_output_directory(out_dir):
    (out_dir / "keep.txt").write_text("existing", encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", str(DIAGNOSE), "--input-zmx", str(sample_zmx("cooke")),
                             "--output-dir", str(out_dir)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2
    assert "non-empty" in result.stderr
    assert sorted(p.name for p in out_dir.iterdir()) == ["keep.txt"]
