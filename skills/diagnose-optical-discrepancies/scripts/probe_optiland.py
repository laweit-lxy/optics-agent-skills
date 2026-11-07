#!/usr/bin/env python3
"""Read-only Optiland probe of a ZMX prescription in the optics-probe/1 schema.

Run with the design-optical-systems environment. Reuses that skill's pinned
entry for path safety, hashing and atomic output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "design-optical-systems" / "scripts"))

import optiland_regression as entry  # noqa: E402  (sets the process-local runtime)
from optiland.materials import Material  # noqa: E402

be = entry.be
PUPILS = ((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0))


def _scalar(value) -> float:
    return float(be.to_numpy(value).ravel()[0])


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _material(surface, wavelengths: list[float]) -> tuple[dict | None, list[float]]:
    medium = surface.material_post
    n = [_scalar(medium.n(w)) for w in wavelengths]
    name = getattr(medium, "name", None)
    if name is None:
        if all(abs(v - 1.0) < 1e-12 for v in n):
            return None, n
        return {"name": None, "catalog": "ideal"}, n
    return {"name": name, "catalog": getattr(medium, "reference", None)}, n


def _working_fno(optic) -> float:
    """Working f/# from the paraxial marginal ray, the definition RayOptics reports."""
    _, slopes = optic.paraxial.marginal_ray()
    n_image = _scalar(optic.surfaces[-1].material_post.n(optic.primary_wavelength))
    return 1.0 / (2.0 * n_image * abs(float(be.to_numpy(slopes).ravel()[-1])))


def probe(path: Path, overrides: dict[str, dict], ray_aiming: str | None,
          object_distance: float | None = None) -> dict:
    optic = entry.load_zemax_file(str(path))
    if object_distance is not None:
        optic.updater.set_thickness(object_distance, 0)
    applied = {}
    for index_text, spec in sorted(overrides.items(), key=lambda item: int(item[0])):
        optic.set_material(Material(spec["name"], spec["catalog"].lower()), int(index_text))
        applied[index_text] = spec
    if ray_aiming:
        optic.set_ray_aiming(ray_aiming)
    wavelengths = [float(w) for w in optic.wavelengths.get_wavelengths()]
    primary = float(optic.primary_wavelength)
    surfaces = []
    for index, surface in enumerate(optic.surfaces):
        material, n = _material(surface, wavelengths)
        radius = float(be.to_numpy(surface.geometry.radius))
        thickness = float(be.to_numpy(surface.thickness))
        surfaces.append({"index": index, "radius_mm": _finite_or_none(radius),
                         "thickness_mm": _finite_or_none(thickness), "material": material, "n": n})
    rays = []
    fields = [list(map(float, coords)) for coords in optic.fields.get_field_coords()]
    for field_index, (hx, hy) in enumerate(fields):
        for px, py in PUPILS:
            optic.trace_generic(hx, hy, px, py, primary)
            rays.append({"field_index": field_index, "pupil": [px, py], "wavelength_um": primary,
                         "x_mm": _scalar(optic.surfaces.x[-1]), "y_mm": _scalar(optic.surfaces.y[-1])})
    return {
        "engine": "optiland",
        "engine_version": entry._version("optiland"),
        "settings": {"ray_aiming": ray_aiming or "paraxial (default)", "material_overrides": applied,
                     "object_distance_mm": object_distance},
        "wavelengths_um": wavelengths,
        "primary_wavelength_um": primary,
        "fields": {"normalized": fields, "max": float(optic.fields.max_field)},
        "stop_index": int(optic.surfaces.stop_index),
        "surfaces": surfaces,
        "first_order": {"efl_mm": float(optic.paraxial.f2()), "fno_working": _working_fno(optic)},
        "rays": rays,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-zmx", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--material-overrides", default="{}",
                        help='JSON {"surface index": {"name": "F2", "catalog": "hikari"}}')
    parser.add_argument("--ray-aiming", choices=["paraxial", "iterative", "robust"])
    parser.add_argument("--object-distance", type=float,
                        help="replace the object distance in mm (default: as imported)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    source = entry._local_input(args.input_zmx)
    manifest = entry._package_code_manifest()
    if not manifest["matches_pin"]:
        raise entry.RegressionError("installed Optiland source does not match the pinned code manifest")
    before = entry._sha256(source)
    report = probe(source, json.loads(args.material_overrides),
                   None if args.ray_aiming in (None, "paraxial") else args.ray_aiming,
                   args.object_distance)
    after = entry._sha256(source)
    if before != after:
        raise entry.RegressionError("input ZMX changed during read-only probe")
    report = {"schema": "optics-probe/1",
              "source": {"path": str(source), "sha256_before": before, "sha256_after": after},
              "integrity": {"optiland_code_manifest": {key: manifest[key] for key in
                                                       ("sha256", "file_count", "matches_pin")}},
              **report}
    entry._atomic_json(Path(args.output), report, args.force, {source})
    print(json.dumps({"status": "OK", "engine": "optiland", "output": str(Path(args.output).resolve())}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (entry.RegressionError, FileExistsError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
