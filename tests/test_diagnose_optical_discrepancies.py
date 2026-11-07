"""Probes and the end-to-end diagnosis on the bundled samples.

Needs both engine environments (design-optical-systems and
cross-check-optical-designs), found as in optics_agent_skills.engines.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import REPO, SAMPLES, read_report, sample_reference, sample_zmx, sha256

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
    "cooke": ("UNRESOLVED", {"material_catalog", "ray_aiming"}),
    "double-gauss": ("UNRESOLVED", {"ray_aiming"}),
    "hubble": ("EXPLAINED", {"object_distance"}),
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


@pytest.mark.parametrize("name", SAMPLES)
def test_diagnosis_matches_qualified_outcome(name, out_dir):
    zmx = sample_zmx(name)
    before = sha256(zmx)
    result = subprocess.run([sys.executable, "-I", str(DIAGNOSE), "--input-zmx", str(zmx),
                             "--output-dir", str(out_dir / name), "--reference-json", str(sample_reference(name))],
                            capture_output=True, text=True, encoding="utf-8", timeout=1800)
    status, confirmed = EXPECTED[name]
    assert result.returncode == (0 if status == "EXPLAINED" else 1), result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == status
    report = read_report(out_dir / name / "diagnosis.json")
    assert sha256(zmx) == before
    assert report["schema"] == "optics-diagnosis/1" and report["status"] == status
    assert {c["category"] for c in report["causes"]} == confirmed
    assert all(c["confirmed_by"] for c in report["causes"])
    if name == "cooke":
        swap = next(e for e in report["experiments"] if e["name"] == "material_catalog_swap")
        assert swap["kept"] and swap["efl_mm_after"] == pytest.approx(COOKE_EFL_HIKARI_MM, rel=1e-12)
        assert report["reference"]["rayoptics"]["agrees"] and not report["reference"]["optiland"]["agrees"]
    if name == "hubble":
        assert report["unresolved"] == []
        assert report["reference"]["optiland"]["agrees"] and report["reference"]["rayoptics"]["agrees"]


def test_refuses_non_empty_output_directory(out_dir):
    (out_dir / "keep.txt").write_text("existing", encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", str(DIAGNOSE), "--input-zmx", str(sample_zmx("cooke")),
                             "--output-dir", str(out_dir)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2
    assert "non-empty" in result.stderr
    assert sorted(p.name for p in out_dir.iterdir()) == ["keep.txt"]
