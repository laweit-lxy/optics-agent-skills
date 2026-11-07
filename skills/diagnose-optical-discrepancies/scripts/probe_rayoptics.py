#!/usr/bin/env python3
"""Read-only RayOptics probe of a ZMX prescription in the optics-probe/1 schema.

Run with the cross-check-optical-designs environment. Reuses that skill's pinned
entry, including its declared-GCAT catalog policy, path safety and atomic output.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / "cross-check-optical-designs" / "scripts"))

import rayoptics_crosscheck as entry  # noqa: E402

PUPILS = ((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0))


def _radius(cv: float) -> float | None:
    return None if cv == 0 else 1.0 / cv


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def probe(path: Path) -> dict:
    from rayoptics.raytr import trace

    with entry._rayoptics_runtime() as read_lens_file:
        model, _ = read_lens_file(path)
        sm, osp = model["sm"], model["osp"]
        wavelengths_nm = [float(w) for w in osp["wvls"].wavelengths]
        primary_nm = float(osp["wvls"].central_wvl)
        surfaces = []
        for index, ifc in enumerate(sm.ifcs):
            gap = sm.gaps[index] if index < len(sm.gaps) else None
            material, n, thickness = None, [], None
            if gap is not None:
                medium = gap.medium
                n = [float(medium.rindex(w)) for w in wavelengths_nm]
                thickness = _finite_or_none(float(gap.thi))
                if not all(abs(v - 1.0) < 1e-12 for v in n):
                    catalog = getattr(medium, "catalog_name", None)
                    material = {"name": medium.name(), "catalog": catalog() if callable(catalog) else None}
            else:
                n = [1.0] * len(wavelengths_nm)
            surfaces.append({"index": index, "radius_mm": _radius(float(ifc.profile.cv)),
                             "thickness_mm": thickness, "material": material, "n": n})
        fields = osp["fov"].fields
        max_field = float(osp["fov"].value)
        rays = []
        for field_index, field in enumerate(fields):
            for pupil in PUPILS:
                pkg, error = trace.trace_ray(model, list(pupil), field, primary_nm,
                                             check_apertures=False, apply_vignetting=True)
                point = pkg.ray[-1].p if error is None else (math.nan, math.nan)
                rays.append({"field_index": field_index, "pupil": list(pupil),
                             "wavelength_um": primary_nm / 1000.0,
                             "x_mm": float(point[0]), "y_mm": float(point[1]),
                             "error": None if error is None else type(error).__name__})
        first_order = model["analysis_results"]["parax_data"][2]
        return {
            "engine": "rayoptics",
            "engine_version": entry._installed_commit() or "unknown",
            "settings": {"ray_aiming": "rayoptics default (chief ray aimed at stop center)",
                         "material_overrides": {}},
            "wavelengths_um": [w / 1000.0 for w in wavelengths_nm],
            "primary_wavelength_um": primary_nm / 1000.0,
            "fields": {"normalized": [[f.x / max_field if max_field else 0.0,
                                       f.y / max_field if max_field else 0.0] for f in fields],
                       "max": max_field},
            "stop_index": int(sm.stop_surface),
            "surfaces": surfaces,
            # RayOptics fno is the working f/# from the paraxial marginal ray slope.
            "first_order": {"efl_mm": float(first_order.efl), "fno_working": float(first_order.fno)},
            "rays": rays,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-zmx", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    source = entry._local_file(args.input_zmx, "input", {".zmx"})
    output = Path(args.output).expanduser()
    before = entry._sha256(source)
    report = probe(source)
    after = entry._sha256(source)
    if before != after:
        raise entry.CrossCheckError("input ZMX changed during read-only probe")
    manifest = entry._package_manifest()
    report = {"schema": "optics-probe/1",
              "source": {"path": str(source), "sha256_before": before, "sha256_after": after},
              "integrity": {"rayoptics_source_manifest": {key: manifest[key] for key in
                                                          ("sha256", "file_count", "manifest_matches_frozen",
                                                           "commit_matches_pin", "matches_pin")},
                            "rii_catalog_snapshot": entry._rii_snapshot()["matches_pin"]},
              **report}
    entry._atomic_json(output, report, args.force, {source})
    print(json.dumps({"status": "OK", "engine": "rayoptics", "output": str(output.resolve())}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (entry.CrossCheckError, FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
