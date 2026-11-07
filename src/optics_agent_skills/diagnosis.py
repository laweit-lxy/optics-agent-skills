"""Compare two optics-probe/1 reports and classify their differences.

Pure standard library, so the same logic serves the CLI, the agent skill and the
MCP server. Elimination experiments are planned here and executed by
``optics_agent_skills.engines``.
"""
from __future__ import annotations

import math
from typing import Any

# Agreement thresholds. Geometry and indices are parser outputs and should agree
# to rounding. The first-order tolerance is tighter than the cross-check default
# (1e-4) so that a glass-catalog or conjugate difference of a few ppm still
# registers; the ray tolerance is 0.1 um at the image.
GEOMETRY_ATOL_MM = 1e-9
INDEX_ATOL = 1e-7
FIRST_ORDER_RTOL = 1e-6
RAY_ATOL_MM = 1e-4
INFINITE_MM = 1e9

CATEGORIES = {
    "importer": "The engines read different geometry or structure from the same file.",
    "material_catalog": "The engines resolved a glass to different catalog data.",
    "object_distance": "One engine places the object at infinity, the other at a large finite distance; "
                       "the image shifts by about f^2/z and the working f/# changes with the conjugate.",
    "paraxial_convention": "Inputs agree but first-order quantities differ.",
    "ray_aiming": "Real rays differ off axis; pupil or ray-aiming conventions differ.",
}
# Experiment name -> category it tests. engines.diagnose runs them in this order,
# each on top of the previous one.
EXPERIMENTS = {"material_catalog_swap": "material_catalog", "object_distance": "object_distance",
               "ray_aiming": "ray_aiming"}


# Importer findings that make the output comparison meaningless: no experiment
# runs and the status cannot be AGREE or EXPLAINED.
BLOCKING_DETAILS = {"surface count differs", "wavelengths differ", "primary wavelength differs",
                    "fields differ", "rays traced at different wavelengths"}
PROBE_KEYS = ("engine", "wavelengths_um", "primary_wavelength_um", "fields", "stop_index", "surfaces",
              "first_order", "rays")


class ProbeError(ValueError):
    """A probe report is incomplete, so the two engines cannot be compared."""


def validate_probe(probe: dict) -> None:
    missing = [key for key in PROBE_KEYS if key not in probe]
    missing += [f"first_order.{key}" for key in ("efl_mm", "fno_working") if key not in probe.get("first_order", {})]
    missing += [f"fields.{key}" for key in ("normalized", "max") if key not in probe.get("fields", {})]
    if missing:
        raise ProbeError(f"{probe.get('engine', 'probe')} report is missing {', '.join(missing)}")
    wavelengths = len(probe["wavelengths_um"])
    short = [s["index"] for s in probe["surfaces"] if len(s["n"]) != wavelengths]
    if short:
        raise ProbeError(f"{probe['engine']} report has {wavelengths} wavelengths but a different number "
                         f"of indices on surfaces {short}")
    incomplete = [r.get("field_index") for r in probe["rays"]
                  if any(key not in r for key in ("field_index", "pupil", "wavelength_um", "x_mm", "y_mm"))]
    if incomplete:
        raise ProbeError(f"{probe['engine']} report has incomplete rays in fields {incomplete}")
    keys = [_ray_key(r) for r in probe["rays"]]
    if len(keys) != len(set(keys)):
        raise ProbeError(f"{probe['engine']} report repeats a ray")


def _number(value: Any) -> float:
    """A reported number as float; reports store non-finite values as strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return math.nan
    return float(value)


def _length(value: float | None) -> float | None:
    if value is None or not math.isfinite(value) or abs(value) >= INFINITE_MM:
        return None
    return value


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


def _same_length(a: float | None, b: float | None) -> bool:
    a, b = _length(a), _length(b)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= GEOMETRY_ATOL_MM + 1e-12 * max(abs(a), abs(b))


def _material_key(material: dict | None) -> tuple[str, str] | None:
    if material is None:
        return None
    return ((material.get("name") or "").casefold(), (material.get("catalog") or "").casefold())


def compare_inputs(a: dict, b: dict) -> list[dict[str, Any]]:
    """Findings about the prescription each engine actually built."""
    findings: list[dict[str, Any]] = []
    sa, sb = a["surfaces"], b["surfaces"]
    if len(sa) != len(sb):
        return [{"category": "importer", "detail": "surface count differs",
                 "evidence": {a["engine"]: len(sa), b["engine"]: len(sb)}}]
    if a["stop_index"] != b["stop_index"]:
        findings.append({"category": "importer", "detail": "stop surface differs",
                         "evidence": {a["engine"]: a["stop_index"], b["engine"]: b["stop_index"]}})
    if [round(w, 9) for w in a["wavelengths_um"]] != [round(w, 9) for w in b["wavelengths_um"]]:
        findings.append({"category": "importer", "detail": "wavelengths differ",
                         "evidence": {a["engine"]: a["wavelengths_um"], b["engine"]: b["wavelengths_um"]}})
    if round(a["primary_wavelength_um"], 9) != round(b["primary_wavelength_um"], 9):
        findings.append({"category": "importer", "detail": "primary wavelength differs",
                         "evidence": {a["engine"]: a["primary_wavelength_um"],
                                      b["engine"]: b["primary_wavelength_um"]}})
    fa, fb = a["fields"], b["fields"]
    if (not _rel(_number(fa["max"]), _number(fb["max"])) <= 1e-9 or len(fa["normalized"]) != len(fb["normalized"])
            or any(not abs(p - q) <= 1e-9 for u, v in zip(fa["normalized"], fb["normalized"]) for p, q in zip(u, v))):
        findings.append({"category": "importer", "detail": "fields differ",
                         "evidence": {a["engine"]: fa, b["engine"]: fb}})
    wb = {_ray_key(r): round(r["wavelength_um"], 9) for r in b["rays"]}
    ray_wavelengths = sorted({(round(r["wavelength_um"], 9), wb[_ray_key(r)]) for r in a["rays"]
                              if _ray_key(r) in wb and round(r["wavelength_um"], 9) != wb[_ray_key(r)]})
    if ray_wavelengths:
        findings.append({"category": "importer", "detail": "rays traced at different wavelengths",
                         "evidence": {"pairs_um": [list(p) for p in ray_wavelengths]}})
    za, zb = sa[0]["thickness_mm"], sb[0]["thickness_mm"]
    if _same_length(za, zb) and (za is None) != (zb is None):
        finite = za if za is not None else zb
        efl = _number(a["first_order"]["efl_mm"])
        findings.append({"category": "object_distance", "surface": 0,
                         "detail": "object at infinity in one engine, at a large finite distance in the other",
                         "evidence": {a["engine"]: za, b["engine"]: zb, "finite_distance_mm": finite,
                                      "estimated_image_shift_mm": efl * efl / finite}})
    last = len(sa) - 1
    for x, y in zip(sa, sb):
        index = x["index"]
        if not _same_length(x["radius_mm"], y["radius_mm"]):
            findings.append({"category": "importer", "surface": index, "detail": "radius differs",
                             "evidence": {a["engine"]: x["radius_mm"], b["engine"]: y["radius_mm"]}})
        if index != last and not _same_length(x["thickness_mm"], y["thickness_mm"]):
            findings.append({"category": "importer", "surface": index, "detail": "thickness differs",
                             "evidence": {a["engine"]: x["thickness_mm"], b["engine"]: y["thickness_mm"]}})
        catalog_differs = _material_key(x["material"]) != _material_key(y["material"])
        index_delta = max((abs(p - q) for p, q in zip(x["n"], y["n"])), default=0.0)
        if catalog_differs or index_delta > INDEX_ATOL:
            findings.append({
                "category": "material_catalog", "surface": index,
                "detail": "different catalog" if catalog_differs else "same catalog, different index data",
                "evidence": {a["engine"]: x["material"], b["engine"]: y["material"],
                             "max_index_delta": index_delta,
                             "wavelengths_um": a["wavelengths_um"]},
            })
    return findings


def compare_first_order(a: dict, b: dict) -> list[dict[str, Any]]:
    findings = []
    for key in ("efl_mm", "fno_working"):
        raw_p, raw_q = a["first_order"][key], b["first_order"][key]
        p, q = _number(raw_p), _number(raw_q)
        non_finite = [e for e, v in ((a["engine"], p), (b["engine"], q)) if not math.isfinite(v)]
        if non_finite or _rel(p, q) > FIRST_ORDER_RTOL:
            findings.append({"category": "first_order", "metric": key, "non_finite": non_finite,
                             "evidence": {a["engine"]: raw_p, b["engine"]: raw_q,
                                          "relative_delta": None if non_finite or not q else (p - q) / q}})
    return findings


def _ray_key(ray: dict) -> tuple:
    return ray["field_index"], tuple(ray["pupil"])


def compare_rays(a: dict, b: dict) -> list[dict[str, Any]]:
    """Ray differences over the rays of both reports; a ray one report lacks counts as untraced there."""
    ra, rb = {_ray_key(r): r for r in a["rays"]}, {_ray_key(r): r for r in b["rays"]}
    findings = []
    for key in list(ra) + [k for k in rb if k not in ra]:
        ray, other = ra.get(key), rb.get(key)
        pa = (_number(ray["x_mm"]), _number(ray["y_mm"])) if ray else (math.nan, math.nan)
        pb = (_number(other["x_mm"]), _number(other["y_mm"])) if other else (math.nan, math.nan)
        missing = [p["engine"] for p, r in ((a, ray), (b, other)) if r is None]
        untraced = [p["engine"] for p, xy in ((a, pa), (b, pb)) if not all(map(math.isfinite, xy))]
        delta = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        if untraced or delta > RAY_ATOL_MM:
            findings.append({"category": "real_ray", "field_index": key[0], "pupil": list(key[1]),
                             "ray": "chief" if key[1] == (0.0, 0.0) else "marginal",
                             "untraced": untraced, "missing": missing,
                             "evidence": {a["engine"]: None if a["engine"] in untraced else list(pa),
                                          b["engine"]: None if b["engine"] in untraced else list(pb),
                                          "distance_mm": None if untraced else delta}})
    return findings


def compare(a: dict, b: dict) -> dict[str, Any]:
    validate_probe(a)
    validate_probe(b)
    return {"inputs": compare_inputs(a, b), "first_order": compare_first_order(a, b),
            "rays": compare_rays(a, b)}


def catalog_overrides(target: dict, source: dict, findings: list[dict]) -> dict[str, dict]:
    """Material overrides that make ``target`` use the catalogs ``source`` resolved."""
    overrides = {}
    for finding in findings:
        if finding["category"] != "material_catalog":
            continue
        material = source["surfaces"][finding["surface"]]["material"]
        if material and material.get("name") and material.get("catalog"):
            overrides[str(finding["surface"])] = {"name": material["name"], "catalog": material["catalog"]}
    return overrides


def object_distance_effect(findings: list[dict], fno: float) -> dict[str, float] | None:
    """Estimated effect of a finite stand-in for an infinite object, or None."""
    for finding in findings:
        if finding["category"] == "object_distance":
            distance = finding["evidence"]["finite_distance_mm"]
            shift = finding["evidence"]["estimated_image_shift_mm"]
            efl = math.sqrt(abs(shift) * distance)
            return {"finite_distance_mm": distance, "image_shift_mm": shift,
                    "edge_ray_mm": abs(shift) / (2.0 * _number(fno)), "relative_working_fno": efl / distance}
    return None


def object_distance_matters(effect: dict[str, float]) -> bool:
    """False only when both estimates are finite and below tolerance."""
    return not (effect["edge_ray_mm"] <= RAY_ATOL_MM and effect["relative_working_fno"] <= FIRST_ORDER_RTOL)


def reference_agreement(probes: dict[str, dict], reference_efl: float | None) -> dict[str, Any] | None:
    if reference_efl is None:
        return None
    return {engine: {"efl_mm": p["first_order"]["efl_mm"],
                     "relative_delta": (_number(p["first_order"]["efl_mm"]) - reference_efl) / reference_efl,
                     "agrees": _rel(_number(p["first_order"]["efl_mm"]), reference_efl) <= FIRST_ORDER_RTOL}
            for engine, p in probes.items()} | {"reference_efl_mm": reference_efl}


def blocking(inputs: list[dict]) -> list[dict]:
    """Input findings after which the outputs no longer describe the same rays."""
    return [f for f in inputs if f["category"] == "importer" and f["detail"] in BLOCKING_DETAILS]


def _first_order_key(finding: dict) -> str:
    return finding["metric"]


def _ray_finding_key(finding: dict) -> tuple:
    return finding["field_index"], tuple(finding["pupil"])


def step(state: dict, result: dict) -> dict[str, Any]:
    """Differences one experiment removed, and the state after it.

    A ray the experiment could not trace is never credited to it. A difference it
    had keeps its previous state; a ray that agreed before becomes an untraced
    difference, so a kept experiment cannot hide it.
    """
    before_rays = {_ray_finding_key(f): f for f in state["rays"]}
    after_rays, untraced = {}, []
    for finding in result["rays"]:
        key = _ray_finding_key(finding)
        previous = before_rays.get(key)
        if finding["untraced"] and not (previous and previous["untraced"]):
            untraced.append(key)
            after_rays[key] = previous or finding
        else:
            after_rays[key] = finding
    after_fo = {_first_order_key(f) for f in result["first_order"]}
    removed = ([f for f in state["first_order"] if _first_order_key(f) not in after_fo]
               + [f for k, f in before_rays.items() if k not in after_rays and k not in untraced])
    return {"removed": removed, "untraced": [[k[0], list(k[1])] for k in untraced],
            "state": {"inputs": result["inputs"], "first_order": result["first_order"],
                      "rays": list(after_rays.values())}}


def conclude(baseline: dict, experiments: list[dict]) -> dict[str, Any]:
    """Turn baseline differences and cumulative experiments into causes and open items.

    Status follows the output differences (first-order and rays); input differences
    no experiment tied to an output difference are listed separately.
    Experiments are applied in order. One that removes a difference is kept and the
    next builds on it; one that removes nothing is reverted. A difference is
    attributed to the first experiment after which it disappears.
    """
    causes, unresolved = [], []
    inputs = baseline["inputs"]
    state = baseline
    for experiment in experiments:
        if experiment["status"] != "RAN":
            continue
        outcome = step(state, experiment["result"])
        category = EXPERIMENTS[experiment["name"]]
        if outcome["removed"]:
            causes.append({"category": category, "explanation": CATEGORIES[category],
                           "input_findings": [f for f in inputs if f["category"] == category],
                           "explains": outcome["removed"], "confirmed_by": experiment["name"]})
            state = outcome["state"]
    first_order = state["first_order"]
    rays = [f for f in state["rays"] if not f["untraced"]]
    untraced = [f for f in state["rays"] if f["untraced"]]
    not_comparable = blocking(inputs)
    if not_comparable:
        unresolved.append({"category": "not_comparable", "explanation":
                           "The engines built different surfaces, wavelengths or fields, so their outputs do "
                           "not describe the same rays; resolve the import difference first.",
                           "findings": not_comparable})
    confirmed = {c["category"] for c in causes}
    without_effect = [{"category": category, "explanation": CATEGORIES[category],
                       "findings": [f for f in inputs if f["category"] == category]}
                      for category in ("importer", "material_catalog", "object_distance")
                      if category not in confirmed and any(f["category"] == category for f in inputs)]
    if first_order:
        importer = any(f["category"] == "importer" for f in inputs)
        unresolved.append({"category": "first_order", "explanation":
                           ("First-order quantities still differ; the untested importer differences are "
                            "candidates." if importer else CATEGORIES["paraxial_convention"]),
                           "findings": first_order})
    if rays:
        unresolved.append({"category": "real_ray", "explanation":
                           "Real-ray intercepts still differ after the experiments; pupil coordinate "
                           "definitions or vignetting conventions remain candidates.",
                           "findings": rays})
    if untraced:
        unresolved.append({"category": "untraced_ray", "explanation":
                           "These rays have no valid intercept in at least one engine under the final "
                           "settings (not traced, or missing from a report), so no explanation covers them.",
                           "findings": untraced})
    differs = bool(baseline["first_order"] or baseline["rays"] or not_comparable)
    status = "AGREE" if not differs else ("EXPLAINED" if not unresolved else "UNRESOLVED")
    return {"status": status, "causes": causes, "unresolved": unresolved,
            "input_differences_without_confirmed_effect": without_effect}
