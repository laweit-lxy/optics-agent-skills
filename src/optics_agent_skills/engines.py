"""Run the pinned engine entries in their own environments.

Each skill keeps its own pinned environment (the engines pin different NumPy
versions), so the core never imports an engine. It runs skill scripts with the
configured interpreter and reads their JSON reports.

Interpreters come from environment variables, falling back to
``<repo>/.venv-<skill>``:

- ``OPTICS_SKILLS_PYTHON_DESIGN``: design-optical-systems (Optiland)
- ``OPTICS_SKILLS_PYTHON_CROSSCHECK``: cross-check-optical-designs (RayOptics)
- ``OPTICS_SKILLS_PYTHON_ANALYZE``: analyze-optical-designs (Chromatix/Prysm)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import diagnosis

REPO = Path(__file__).resolve().parents[2]
SKILLS = Path(os.environ.get("OPTICS_SKILLS_ROOT", REPO / "skills")).resolve()

ENGINES = {
    "design": ("design-optical-systems", "OPTICS_SKILLS_PYTHON_DESIGN"),
    "crosscheck": ("cross-check-optical-designs", "OPTICS_SKILLS_PYTHON_CROSSCHECK"),
    "analyze": ("analyze-optical-designs", "OPTICS_SKILLS_PYTHON_ANALYZE"),
}
TIMEOUT_S = 1800


class EngineError(RuntimeError):
    """An engine could not be located or exited abnormally."""


def interpreter(engine: str) -> Path:
    skill, variable = ENGINES[engine]
    configured = os.environ.get(variable)
    candidates = [Path(configured)] if configured else [
        REPO / f".venv-{skill}" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise EngineError(f"no interpreter for {skill}; install skills/{skill}/requirements.txt "
                      f"into an environment and set {variable}")


def local_zmx(path_text: str | os.PathLike) -> Path:
    text = str(path_text)
    if "://" in text:
        raise ValueError("URLs are not accepted; provide a local .zmx path")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("the .zmx path must be absolute")
    if path.suffix.lower() != ".zmx" or not path.is_file():
        raise ValueError(f"not a local .zmx file: {path}")
    return path


def skills_root() -> Path:
    """The skills folder; the core runs from a repository checkout or an editable install."""
    if not SKILLS.is_dir():
        raise EngineError(f"skills folder not found at {SKILLS}; install from a repository checkout "
                          "(pip install -e) or set OPTICS_SKILLS_ROOT")
    return SKILLS


def run_script(engine: str, script: Path, *args: str | os.PathLike) -> subprocess.CompletedProcess[str]:
    skills_root()
    command = [str(interpreter(engine)), "-I", str(script), *map(str, args)]
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT_S, env=env)


def _report(result: subprocess.CompletedProcess[str], output: Path, accepted: set[int]) -> dict[str, Any]:
    if result.returncode not in accepted or not output.is_file():
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        raise EngineError(f"engine exited {result.returncode}: " + " | ".join(tail))
    return json.loads(output.read_text(encoding="utf-8"))


def analyze_prescription(zmx: str | os.PathLike, output: Path, force: bool = False) -> dict[str, Any]:
    script = SKILLS / "design-optical-systems" / "scripts" / "optiland_regression.py"
    args = ["--input-zmx", local_zmx(zmx), "--output", output] + (["--force"] if force else [])
    return _report(run_script("design", script, *args), output, {0, 1})


def cross_check(zmx: str | os.PathLike, output: Path, reference_json: str | None = None,
                force: bool = False) -> dict[str, Any]:
    script = SKILLS / "cross-check-optical-designs" / "scripts" / "rayoptics_crosscheck.py"
    args = ["--input-zmx", local_zmx(zmx), "--output", output]
    args += ["--reference-json", reference_json] if reference_json else []
    args += ["--force"] if force else []
    return _report(run_script("crosscheck", script, *args), output, {0, 1})


def wave_self_test(output: Path) -> dict[str, Any]:
    script = SKILLS / "analyze-optical-designs" / "scripts" / "optics_regression.py"
    return _report(run_script("analyze", script, "--self-test", "--output", output), output, {0, 1})


def probe(engine: str, zmx: Path, output: Path, overrides: dict | None = None,
          ray_aiming: str | None = None, object_distance: float | None = None,
          force: bool = False) -> dict[str, Any]:
    scripts = SKILLS / "diagnose-optical-discrepancies" / "scripts"
    if engine == "design":
        args = ["--material-overrides", json.dumps(overrides or {})]
        args += ["--ray-aiming", ray_aiming] if ray_aiming else []
        args += ["--object-distance", repr(object_distance)] if object_distance is not None else []
        args += ["--force"] if force else []
        result = run_script("design", scripts / "probe_optiland.py", "--input-zmx", zmx,
                            "--output", output, *args)
    else:
        result = run_script("crosscheck", scripts / "probe_rayoptics.py", "--input-zmx", zmx,
                            "--output", output, *(["--force"] if force else []))
    return _report(result, output, {0})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_safe(value: Any) -> Any:
    """Strict JSON: non-finite floats become the strings the probes use."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    return value


def _refuse_aliases(outputs: list[Path], inputs: list[Path]) -> None:
    """Refuse output paths that are links to, or hard links of, an input file."""
    for output in outputs:
        if output.is_symlink():
            raise ValueError(f"refusing to write through a link: {output}")
        if not output.exists():
            continue
        for source in inputs:
            if source.exists() and os.path.samefile(output, source):
                raise ValueError(f"output {output} is the same file as input {source}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write to a temporary file, then replace: never write into an existing file."""
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(_json_safe(payload), handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _reference_efl(path: str | None) -> float | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    try:
        return float(data["first_order"]["effective_focal_length_mm"]["value"])
    except (KeyError, TypeError) as exc:
        raise ValueError("reference JSON needs first_order.effective_focal_length_mm.value") from exc


def diagnose(zmx: str | os.PathLike, output_dir: Path, reference_json: str | None = None,
             force: bool = False) -> dict[str, Any]:
    """Probe both engines, run elimination experiments and write diagnosis.json."""
    source = local_zmx(zmx)
    output_dir = Path(output_dir).expanduser().resolve()
    final = output_dir / "diagnosis.json"
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise FileExistsError(f"refusing to write into non-empty directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = [source] + ([Path(reference_json).expanduser()] if reference_json else [])
    planned = [final, output_dir / "probe-optiland.json", output_dir / "probe-rayoptics.json"]
    planned += [output_dir / f"probe-optiland-{name.replace('_', '-')}.json" for name in diagnosis.EXPERIMENTS]
    _refuse_aliases(planned, inputs)
    source_sha256 = _sha256(source)
    reference_efl = _reference_efl(reference_json)

    optiland = probe("design", source, output_dir / "probe-optiland.json", force=force)
    rayoptics = probe("crosscheck", source, output_dir / "probe-rayoptics.json", force=force)
    baseline = diagnosis.compare(optiland, rayoptics)

    # Experiments on Optiland; RayOptics stays fixed. Each runs only while the
    # difference it targets is present. A setting that removes a difference is kept
    # for the next experiment; one that removes nothing is reverted.
    experiments: list[dict[str, Any]] = []
    kept: dict[str, Any] = {"overrides": {}, "ray_aiming": None, "object_distance": None}
    state = baseline

    def run(name: str, hypothesis: str, **change: Any) -> None:
        nonlocal state
        trial = {**kept, **change}
        result = probe("design", source, output_dir / f"probe-optiland-{name.replace('_', '-')}.json",
                       trial["overrides"], trial["ray_aiming"], trial["object_distance"], force=force)
        comparison = diagnosis.compare(result, rayoptics)
        outcome = diagnosis.step(state, comparison)
        if outcome["removed"]:
            kept.update(change)
            state = outcome["state"]
        experiments.append({"name": name, "status": "RAN", "hypothesis": hypothesis,
                            "settings": {"material_overrides": trial["overrides"],
                                         "ray_aiming": trial["ray_aiming"] or "paraxial",
                                         "object_distance_mm": trial["object_distance"]},
                            "kept": bool(outcome["removed"]), "removed": len(outcome["removed"]),
                            "untraced_rays": outcome["untraced"],
                            "result": comparison, "efl_mm_after": result["first_order"]["efl_mm"]})

    def skip(name: str, reason: str) -> None:
        experiments.append({"name": name, "status": "SKIPPED", "reason": reason})

    def open_differences() -> bool:
        return bool(state["first_order"] or state["rays"])

    def run_experiments() -> None:
        overrides = diagnosis.catalog_overrides(optiland, rayoptics, baseline["inputs"])
        if not overrides:
            skip("material_catalog_swap", "no glass catalog difference")
        elif not open_differences():
            skip("material_catalog_swap", "no first-order or ray difference to explain")
        else:
            run("material_catalog_swap", "Optiland matches RayOptics when it uses RayOptics' glass catalogs",
                overrides=overrides)
        effect = diagnosis.object_distance_effect(baseline["inputs"], rayoptics["first_order"]["fno_working"])
        if effect is None:
            skip("object_distance", "both engines model the object distance the same way")
        elif not diagnosis.object_distance_matters(effect):
            skip("object_distance", f"estimated effect below tolerance: edge ray {effect['edge_ray_mm']:.3g} mm, "
                                    f"working f/# {effect['relative_working_fno']:.3g} relative")
        elif not open_differences():
            skip("object_distance", "no first-order or ray difference left to explain")
        else:
            run("object_distance", "Optiland matches RayOptics when the object sits at RayOptics' finite "
                "distance instead of infinity", object_distance=effect["finite_distance_mm"])
        if not state["rays"]:
            skip("ray_aiming", "no real-ray difference left to explain")
        else:
            run("ray_aiming", "off-axis rays agree when Optiland aims rays at the real stop",
                ray_aiming="iterative")

    not_comparable = diagnosis.blocking(baseline["inputs"])
    if not_comparable:
        for name in diagnosis.EXPERIMENTS:
            skip(name, "inputs not comparable: " + "; ".join(f["detail"] for f in not_comparable))
    else:
        run_experiments()

    conclusion = diagnosis.conclude(baseline, experiments)
    report = {
        "schema": "optics-diagnosis/1",
        "status": conclusion["status"],
        "source": optiland["source"],
        "engines": {p["engine"]: {"version": p["engine_version"], "settings": p["settings"],
                                  "integrity": p.get("integrity")}
                    for p in (optiland, rayoptics)},
        "tolerances": {"geometry_atol_mm": diagnosis.GEOMETRY_ATOL_MM, "index_atol": diagnosis.INDEX_ATOL,
                       "first_order_rtol": diagnosis.FIRST_ORDER_RTOL, "ray_atol_mm": diagnosis.RAY_ATOL_MM},
        "baseline": baseline,
        "experiments": experiments,
        "causes": conclusion["causes"],
        "unresolved": conclusion["unresolved"],
        "input_differences_without_confirmed_effect": conclusion["input_differences_without_confirmed_effect"],
        "reference": diagnosis.reference_agreement({"optiland": optiland, "rayoptics": rayoptics},
                                                   reference_efl),
        "limitations": [
            "Optiland is the adjusted engine in every experiment; RayOptics is held fixed.",
            "An experiment that removes a difference keeps its setting for the next one; one that "
            "removes nothing is reverted. A ray an experiment cannot trace is never credited to it; a ray "
            "that agreed before and cannot be traced under a kept setting stays unresolved.",
            "Rays are compared at the primary wavelength: the chief ray and three pupil-edge rays per field.",
            "Aberration coefficients, spot and MTF are not compared: the engines use different "
            "normalizations, and RayOptics has no MTF.",
            "A confirmed cause explains the difference between the engines; it does not show which "
            "engine matches the manufacturer or OpticStudio unless a reference is supplied.",
        ],
    }
    _write_json(final, report)
    if _sha256(source) != source_sha256:
        raise EngineError(f"input changed during the diagnosis: {source}")
    return report
