"""Unit tests for optics_agent_skills.diagnosis on synthetic optics-probe/1 reports,
and for the output safety of engines.diagnose with the probes replaced by them.

Standard library only: these run without any optics engine installed.
"""
from __future__ import annotations

import copy
import hashlib
import os

import pytest

from optics_agent_skills import diagnosis, engines


def make_probe(engine: str) -> dict:
    return {
        "engine": engine,
        "wavelengths_um": [0.4861, 0.5876, 0.6563],
        "primary_wavelength_um": 0.5876,
        "fields": {"normalized": [[0.0, 0.0], [0.0, 1.0]], "max": 20.0},
        "stop_index": 2,
        "surfaces": [
            {"index": 0, "radius_mm": None, "thickness_mm": None, "material": None, "n": [1.0, 1.0, 1.0]},
            {"index": 1, "radius_mm": 22.0, "thickness_mm": 3.0,
             "material": {"name": "N-BK7", "catalog": "schott"}, "n": [1.522, 1.5168, 1.5143]},
            {"index": 2, "radius_mm": None, "thickness_mm": 40.0, "material": None, "n": [1.0, 1.0, 1.0]},
            {"index": 3, "radius_mm": None, "thickness_mm": None, "material": None, "n": [1.0, 1.0, 1.0]},
        ],
        "first_order": {"efl_mm": 50.0, "fno_working": 5.0},
        "rays": [
            {"field_index": f, "pupil": list(p), "wavelength_um": 0.5876,
             "x_mm": 0.1 * f * p[0], "y_mm": 1.0 * f + 0.2 * p[1]}
            for f in (0, 1) for p in ((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0))
        ],
    }


def ray(probe: dict, field_index: int, pupil: list[float]) -> dict:
    return next(r for r in probe["rays"] if r["field_index"] == field_index and r["pupil"] == pupil)


def ran(name: str, a: dict, b: dict) -> dict:
    return {"name": name, "status": "RAN", "result": diagnosis.compare(a, b)}


def test_identical_probes_agree():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    baseline = diagnosis.compare(a, b)
    assert baseline == {"inputs": [], "first_order": [], "rays": []}
    assert diagnosis.conclude(baseline, [])["status"] == "AGREE"


def test_infinite_object_conventions_and_image_thickness_are_not_importer_findings():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["surfaces"][0]["thickness_mm"] = 1e10
    b["surfaces"][3]["thickness_mm"] = 0.0
    findings = diagnosis.compare_inputs(a, b)
    assert [f["category"] for f in findings] == ["object_distance"]
    evidence = findings[0]["evidence"]
    assert evidence["finite_distance_mm"] == 1e10
    assert abs(evidence["estimated_image_shift_mm"] - 50.0 ** 2 / 1e10) < 1e-18


def test_input_difference_without_output_effect_is_listed_not_a_cause():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["surfaces"][1]["radius_mm"] = 22.001
    baseline = diagnosis.compare(a, b)
    assert [(f["category"], f["detail"]) for f in baseline["inputs"]] == [("importer", "radius differs")]
    conclusion = diagnosis.conclude(baseline, [])
    assert conclusion["causes"] == []
    assert [d["category"] for d in conclusion["input_differences_without_confirmed_effect"]] == ["importer"]
    assert conclusion["status"] == "AGREE"


def test_importer_difference_is_named_when_first_order_stays_unexplained():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["surfaces"][1]["radius_mm"] = 22.001
    b["first_order"]["efl_mm"] = 50.01
    conclusion = diagnosis.conclude(diagnosis.compare(a, b), [])
    assert conclusion["status"] == "UNRESOLVED"
    assert "importer" in conclusion["unresolved"][0]["explanation"]


def test_catalog_swap_confirms_material_cause():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["surfaces"][1]["material"] = {"name": "N-BK7", "catalog": "hikari"}
    b["surfaces"][1]["n"] = [1.522, 1.51681, 1.5143]
    b["first_order"]["efl_mm"] = 50.001
    baseline = diagnosis.compare(a, b)
    assert diagnosis.catalog_overrides(a, b, baseline["inputs"]) == {"1": {"name": "N-BK7", "catalog": "hikari"}}
    swapped = copy.deepcopy(b)
    swapped["engine"] = "optiland"
    conclusion = diagnosis.conclude(baseline, [ran("material_catalog_swap", swapped, b)])
    assert conclusion["status"] == "EXPLAINED"
    cause = conclusion["causes"][0]
    assert (cause["category"], cause["confirmed_by"]) == ("material_catalog", "material_catalog_swap")
    assert [f["metric"] for f in cause["explains"]] == ["efl_mm"]


def test_first_order_difference_without_input_difference_is_unresolved():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["first_order"]["fno_working"] = 5.001
    conclusion = diagnosis.conclude(diagnosis.compare(a, b), [])
    assert conclusion["status"] == "UNRESOLVED"
    assert conclusion["unresolved"][0]["category"] == "first_order"
    assert conclusion["unresolved"][0]["explanation"] == diagnosis.CATEGORIES["paraxial_convention"]


def test_cumulative_experiments_credit_only_what_each_one_removes():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["surfaces"][0]["thickness_mm"] = 1e10
    for r in b["rays"]:
        r["y_mm"] += 0.01  # defocus: every ray differs
    baseline = diagnosis.compare(a, b)
    assert len(baseline["rays"]) == 8

    refocused = copy.deepcopy(b)
    refocused["engine"] = "optiland"
    for f in (1,):
        for p in ([0.0, 0.0], [0.0, 1.0], [0.0, -1.0], [1.0, 0.0]):
            ray(refocused, f, p)["y_mm"] -= 0.002  # off-axis rays still differ
    aimed = copy.deepcopy(refocused)
    ray(aimed, 1, [0.0, 0.0])["y_mm"] += 0.002  # aiming fixes the chief ray only

    conclusion = diagnosis.conclude(baseline, [
        {"name": "material_catalog_swap", "status": "SKIPPED", "reason": "no glass catalog difference"},
        ran("object_distance", refocused, b),
        ran("ray_aiming", aimed, b),
    ])
    by_category = {c["category"]: c for c in conclusion["causes"]}
    assert len(by_category["object_distance"]["explains"]) == 4
    assert {f["field_index"] for f in by_category["object_distance"]["explains"]} == {0}
    assert [(f["field_index"], f["pupil"]) for f in by_category["ray_aiming"]["explains"]] == [(1, [0.0, 0.0])]
    assert conclusion["status"] == "UNRESOLVED"
    assert [u["category"] for u in conclusion["unresolved"]] == ["real_ray"]
    assert len(conclusion["unresolved"][0]["findings"]) == 3


def test_untraced_rays_are_never_credited():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    ray(b, 1, [0.0, 1.0])["y_mm"] += 0.01
    baseline = diagnosis.compare(a, b)
    trial = copy.deepcopy(b)
    trial["engine"] = "optiland"
    for f in trial["rays"]:
        if f["field_index"] == 1:
            f["x_mm"] = f["y_mm"] = "NaN"  # how reports store non-finite values
    outcome = diagnosis.step(baseline, diagnosis.compare(trial, b))
    assert outcome["removed"] == []
    assert len(outcome["untraced"]) == 4
    state = {(f["field_index"], tuple(f["pupil"])): f for f in outcome["state"]["rays"]}
    assert len(state) == 4 and {k[0] for k in state} == {1}
    assert state[(1, (0.0, 1.0))]["untraced"] == []  # the earlier difference is kept as it was
    conclusion = diagnosis.conclude(baseline, [ran("object_distance", trial, b)])
    assert conclusion["causes"] == []
    assert len(conclusion["unresolved"][0]["findings"]) == 1
    assert conclusion["input_differences_without_confirmed_effect"] == []


def test_experiment_that_removes_nothing_is_reverted():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    ray(b, 1, [0.0, 0.0])["y_mm"] += 0.01
    baseline = diagnosis.compare(a, b)
    worse = copy.deepcopy(a)
    ray(worse, 0, [0.0, 1.0])["y_mm"] += 0.01  # adds a difference, removes none
    fixed = copy.deepcopy(b)
    fixed["engine"] = "optiland"
    conclusion = diagnosis.conclude(baseline, [ran("object_distance", worse, b), ran("ray_aiming", fixed, b)])
    assert [(c["category"], len(c["explains"])) for c in conclusion["causes"]] == [("ray_aiming", 1)]
    assert conclusion["status"] == "EXPLAINED"


def test_object_distance_effect_threshold():
    hubble = [{"category": "object_distance",
               "evidence": {"finite_distance_mm": 1e10, "estimated_image_shift_mm": 57600.08 ** 2 / 1e10}}]
    effect = diagnosis.object_distance_effect(hubble, 24.0)
    assert abs(effect["edge_ray_mm"] - 0.006912) < 1e-5
    assert diagnosis.object_distance_matters(effect)
    cooke = [{"category": "object_distance",
              "evidence": {"finite_distance_mm": 1e10, "estimated_image_shift_mm": 50.0 ** 2 / 1e10}}]
    assert not diagnosis.object_distance_matters(diagnosis.object_distance_effect(cooke, 5.0))


def test_reference_agreement_flags_the_engine_that_differs():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    b["first_order"]["efl_mm"] = 50.001
    result = diagnosis.reference_agreement({"optiland": a, "rayoptics": b}, 50.0)
    assert result["optiland"]["agrees"] is True
    assert result["rayoptics"]["agrees"] is False
    assert diagnosis.reference_agreement({"optiland": a}, None) is None


def test_kept_experiment_cannot_hide_a_ray_it_made_untraceable():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    ray(a, 0, [0.0, 0.0])["y_mm"] += 0.01
    baseline = diagnosis.compare(a, b)
    trial = copy.deepcopy(b)
    trial["engine"] = "optiland"
    ray(trial, 1, [0.0, 1.0])["x_mm"] = ray(trial, 1, [0.0, 1.0])["y_mm"] = "NaN"
    conclusion = diagnosis.conclude(baseline, [ran("ray_aiming", trial, b)])
    assert [c["category"] for c in conclusion["causes"]] == ["ray_aiming"]
    assert conclusion["status"] == "UNRESOLVED"
    assert [u["category"] for u in conclusion["unresolved"]] == ["untraced_ray"]
    finding = conclusion["unresolved"][0]["findings"][0]
    assert (finding["field_index"], finding["pupil"], finding["untraced"]) == (1, [0.0, 1.0], ["optiland"])


def test_a_ray_missing_from_one_report_counts_as_untraced():
    a, b = make_probe("optiland"), make_probe("rayoptics")
    a["rays"] = [r for r in a["rays"] if (r["field_index"], r["pupil"]) != (1, [1.0, 0.0])]
    findings = diagnosis.compare_rays(a, b)
    assert [(f["field_index"], f["pupil"], f["untraced"], f["missing"]) for f in findings] == [
        (1, [1.0, 0.0], ["optiland"], ["optiland"])]
    assert diagnosis.conclude(diagnosis.compare(a, b), [])["status"] == "UNRESOLVED"


@pytest.mark.parametrize("value", [float("nan"), "NaN", "Infinity"])
def test_non_finite_first_order_value_is_a_difference(value):
    a, b = make_probe("optiland"), make_probe("rayoptics")
    a["first_order"]["efl_mm"] = value
    findings = diagnosis.compare_first_order(a, b)
    assert [(f["metric"], f["non_finite"]) for f in findings] == [("efl_mm", ["optiland"])]
    assert findings[0]["evidence"]["relative_delta"] is None


@pytest.mark.parametrize("change, detail", [
    (lambda p: p.update(primary_wavelength_um=0.6563), "primary wavelength differs"),
    (lambda p: p["fields"].update(max=30.0), "fields differ"),
    (lambda p: p["fields"].update(normalized=[[0.0, 0.0], [0.0, 0.7]]), "fields differ"),
    (lambda p: [r.update(wavelength_um=0.6563) for r in p["rays"]], "rays traced at different wavelengths"),
])
def test_different_fields_or_wavelengths_are_not_comparable(change, detail):
    a, b = make_probe("optiland"), make_probe("rayoptics")
    change(b)
    baseline = diagnosis.compare(a, b)
    assert [f["detail"] for f in diagnosis.blocking(baseline["inputs"])] == [detail]
    conclusion = diagnosis.conclude(baseline, [])
    assert conclusion["status"] == "UNRESOLVED"
    assert conclusion["unresolved"][0]["category"] == "not_comparable"


@pytest.mark.parametrize("change", [
    lambda p: p.pop("fields"),
    lambda p: p["first_order"].pop("fno_working"),
    lambda p: p["surfaces"][1].update(n=[1.5168]),
    lambda p: p["rays"].append(dict(p["rays"][0])),
    lambda p: p["rays"][0].pop("wavelength_um"),
])
def test_incomplete_probe_report_is_refused(change):
    a, b = make_probe("optiland"), make_probe("rayoptics")
    change(b)
    with pytest.raises(diagnosis.ProbeError):
        diagnosis.compare(a, b)


@pytest.fixture
def stub_source(monkeypatch, tmp_path):
    """A source prescription for engines.diagnose, with both probes replaced by synthetic reports."""
    source = tmp_path / "lens.zmx"
    source.write_text("VERS 1\n", encoding="utf-8")
    reports = {"design": make_probe("optiland"), "crosscheck": make_probe("rayoptics")}
    for report in reports.values():
        report.update(source={"path": str(source)}, engine_version="stub", settings={})
    monkeypatch.setattr(engines, "probe", lambda engine, *args, **kwargs: copy.deepcopy(reports[engine]))
    return source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_diagnosis_refuses_to_write_over_a_hard_link_of_its_input(stub_source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    os.link(stub_source, out / "diagnosis.json")
    before = digest(stub_source)
    with pytest.raises(ValueError, match="same file"):
        engines.diagnose(stub_source, out, force=True)
    assert digest(stub_source) == before


def test_diagnosis_refuses_a_reference_among_its_outputs(stub_source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    reference = out / "probe-optiland.json"
    reference.write_text('{"first_order": {"effective_focal_length_mm": {"value": 50.0}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="same file"):
        engines.diagnose(stub_source, out, str(reference), force=True)


def test_diagnosis_refuses_to_write_through_a_symbolic_link(stub_source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    try:
        os.symlink(stub_source, out / "diagnosis.json")
    except OSError:
        pytest.skip("creating symbolic links needs extra rights on this host")
    before = digest(stub_source)
    with pytest.raises(ValueError, match="link"):
        engines.diagnose(stub_source, out, force=True)
    assert digest(stub_source) == before


def test_forced_diagnosis_replaces_its_own_report(stub_source, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "diagnosis.json").write_text("old", encoding="utf-8")
    before = digest(stub_source)
    report = engines.diagnose(stub_source, out, force=True)
    assert report["status"] == "AGREE"
    assert (out / "diagnosis.json").read_text(encoding="utf-8").startswith("{")
    assert sorted(p.name for p in out.iterdir()) == ["diagnosis.json"]
    assert digest(stub_source) == before


def test_missing_skills_folder_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(engines, "SKILLS", tmp_path / "absent")
    with pytest.raises(engines.EngineError, match="repository checkout"):
        engines.run_script("design", tmp_path / "absent" / "x.py")
