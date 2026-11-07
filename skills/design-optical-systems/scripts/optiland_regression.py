#!/usr/bin/env python3
"""Pinned Optiland optical-design regression and local ZMX analyzer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

# The pinned Optiland import stalls in Numba JIT initialization on this Windows
# host. Cooke sequential analyses do not exercise the scatter/NURBS JIT paths,
# so the regression deliberately disables JIT process-locally and records it.
# Matplotlib is also redirected away from user AppData to an ephemeral cache.
_RUNTIME_CONFIG = tempfile.TemporaryDirectory(prefix="optiland-runtime-")
os.environ["NUMBA_DISABLE_JIT"] = "1"
os.environ["MPLBACKEND"] = "Agg"
os.environ["MPLCONFIGDIR"] = str(Path(_RUNTIME_CONFIG.name) / "matplotlib")

import numpy as np

import optiland
import optiland.backend as be

be.set_backend("numpy")

from optiland.analysis import SpotDiagram
from optiland.fileio import (
    load_optiland_file,
    load_zemax_file,
    save_optiland_file,
    save_zemax_file,
)
from optiland.mtf import FFTMTF
from optiland.psf import FFTPSF
from optiland.samples.objectives import CookeTriplet, DoubleGauss
from optiland.samples.telescopes import HubbleTelescope
from optiland.tolerancing import RangeSampler, SensitivityAnalysis, Tolerancing
from optiland.wavefront import OPD


PINNED_SHA = "bb487f9b56baaf82eaa563750ff351a5ce90d63d"
EXPECTED_PACKAGE_CODE_MANIFEST_SHA256 = "f288c43ae5f75aa841e30029b5decf7740c6fd88b1bf37ddbbbc514165d912a1"
EXPECTED_PACKAGE_CODE_FILE_COUNT = 538
RTOL = 1e-5
ATOL = 1e-7
EXPECTED_EFL_MM = 49.9997830714319
EXPECTED_FNO = 4.99997830714319
EXPECTED_OPD_RMS_WAVES = 0.9709788038168692
EXPECTED_STREHL = 0.3057675703292016
HUBBLE_FIRST_ORDER_OPTICSTUDIO_2023 = {
    "f2": (57600.079948, 2e-3),
    "EPD": (2400.0, 1e-9),
    "EPL": (4910.01, 5e-3),
    "XPD": (289.9321, 5e-5),
    "XPL": (-6958.364, 1e-3),
    "FNO": (24.00003, 1e-5),
}
HUBBLE_RAYS_OPTICSTUDIO_2023 = [
    ((0.0, 0.0, 0.0, 1.0), (0.0, 0.000292798, 0.0, -0.020832193)),
    ((0.0, 0.0, 0.0, 0.7), (0.0, 0.000224337, 0.0, -0.014582932)),
    ((0.0, 1.0, 0.0, 0.0), (0.0, 150.423380108, 0.0, 0.021668821)),
    ((0.0, 1.0, 0.0, 1.0), (0.0, 150.415481283, 0.0, 0.000731952)),
    ((0.0, 1.0, 0.0, -1.0), (0.0, 150.483684128, 0.0, 0.042499115)),
    ((0.0, 0.7, 0.7, 0.0), (0.011252785, 105.43303112, -0.014598926, 0.015153183)),
]
HUBBLE_SPOT_OPTICSTUDIO_2023_MM = {
    0: (2.33518114e-4, 2.92798267e-4),
    1: (2.94822866e-2, 6.03040204e-2),
}
EXPECTED_GEOMETRIC_MM = np.asarray(
    [
        [0.00597244087781219, 0.006286457711247116, 0.00931911440064303],
        [0.03928464835617618, 0.04075295155639047, 0.04772194200606705],
        [0.018909146395329878, 0.022501847359635008, 0.036545592330568866],
    ]
)
EXPECTED_RMS_MM = np.asarray(
    [
        [0.0037913354614487415, 0.004293689564257822, 0.006195618755673686],
        [0.01582480029344623, 0.016918412809703662, 0.019221165873836682],
        [0.013236232767092956, 0.012116688566406967, 0.013648684944411313],
    ]
)
EXPECTED_RADII_MM = [math.inf, 22.01359, -435.76044, -22.21328, 20.29192, 79.68360, -18.39533, math.inf]
EXPECTED_THICKNESS_MM = [math.inf, 3.25896, 6.00755, 0.99997, 4.75041, 2.95208, 42.20778]


class RegressionError(RuntimeError):
    """Raised when a regression or safety check fails."""


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _to_float(value: Any) -> float:
    array = np.asarray(be.to_numpy(value))
    return float(array.item())


def _to_array(values: Any) -> np.ndarray:
    return np.asarray([[ _to_float(item) for item in row ] for row in values], dtype=float)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_remote_or_reparse(path: Path, label: str) -> None:
    """Reject UNC paths and any symlink/junction in an existing path chain."""
    if not path.is_absolute():
        raise RegressionError(f"{label} must use an absolute local path")
    if str(path).startswith("\\\\") or path.anchor.startswith("\\\\"):
        raise RegressionError(f"{label} must not use a UNC/network path")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    cursor = path
    while True:
        try:
            info = os.lstat(cursor)
        except FileNotFoundError:
            pass
        else:
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or (reparse_flag and attributes & reparse_flag):
                raise RegressionError(f"{label} path contains a symlink or reparse point: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


def _local_input(path_text: str) -> Path:
    if "://" in path_text:
        raise RegressionError("URLs are not accepted; provide a local prescription")
    path = Path(path_text).expanduser()
    _reject_remote_or_reparse(path, "input")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RegressionError("input must be a regular file")
    if resolved.suffix.lower() != ".zmx":
        raise RegressionError("--input-zmx requires a .zmx file")
    return resolved


def _package_code_manifest() -> dict[str, Any]:
    """Bind the runtime report to the installed Optiland source-code bytes."""
    root = Path(optiland.__file__).resolve(strict=True).parent
    extensions = {".py", ".pyi", ".typed"}
    files = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() in extensions
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    digest = hashlib.sha256()
    byte_count = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        contents_digest = hashlib.sha256(path.read_bytes()).digest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(contents_digest)
        byte_count += path.stat().st_size
    actual = digest.hexdigest()
    return {
        "algorithm": "sha256(sorted relative UTF-8 path + NUL + per-file SHA-256)",
        "included_extensions": sorted(extensions),
        "excluded": ["__pycache__", ".pyc", ".pyo"],
        "file_count": len(files),
        "byte_count": byte_count,
        "sha256": actual,
        "expected_file_count": EXPECTED_PACKAGE_CODE_FILE_COUNT,
        "expected_sha256": EXPECTED_PACKAGE_CODE_MANIFEST_SHA256,
        "matches_pin": len(files) == EXPECTED_PACKAGE_CODE_FILE_COUNT
        and actual == EXPECTED_PACKAGE_CODE_MANIFEST_SHA256,
    }


def _check(
    name: str,
    passed: bool,
    actual: Any,
    expected: Any,
    note: str = "",
    *,
    required_for_acceptance: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "required_for_acceptance": required_for_acceptance,
        "actual": actual,
        "expected": expected,
        "note": note,
    }


def _surface_summary(optic: Any) -> dict[str, Any]:
    radii = [_to_float(surface.geometry.radius) for surface in optic.surfaces]
    thickness = [_to_float(surface.thickness) for surface in optic.surfaces]
    stops = [index for index, surface in enumerate(optic.surfaces) if bool(surface.is_stop)]
    return {
        "surface_count": int(optic.surfaces.num_surfaces),
        "radii_mm": radii,
        "thickness_mm": thickness,
        "stop_surfaces": stops,
    }


def _image_intercept(
    optic: Any, hx: float, hy: float, px: float, py: float, wavelength: float
) -> tuple[float, float, float, float]:
    """Trace one real ray and return x, y, L, M at the image surface."""
    rays = optic.trace_generic(hx, hy, px, py, wavelength)
    return tuple(
        float(np.asarray(be.to_numpy(getattr(rays, attr))).reshape(-1)[-1])
        for attr in "xyLM"
    )


def _material_signature(optic: Any) -> list[dict[str, Any]]:
    """Record dispersive identity and actual n(lambda) at system wavelengths."""
    signatures: list[dict[str, Any]] = []
    surfaces = optic.to_dict()["surface_group"]["surfaces"]
    wavelengths = [float(value) for value in optic.wavelengths.get_wavelengths()]
    for index, (surface, serialized) in enumerate(
        zip(optic.surfaces, surfaces, strict=True)
    ):
        material = serialized.get("material_post", {})
        if material.get("type") != "Material":
            continue
        signatures.append(
            {
                "surface": index,
                "name": material.get("name"),
                "reference": material.get("reference"),
                "filename": Path(material.get("filename", "")).as_posix(),
                "n_by_wavelength_um": {
                    f"{wavelength:.12g}": _to_float(
                        surface.material_post.n(wavelength)
                    )
                    for wavelength in wavelengths
                },
            }
        )
    return signatures


def _optical_metrics(optic: Any, full_arrays: bool = False) -> dict[str, Any]:
    efl = _to_float(optic.paraxial.f2())
    fno = _to_float(optic.paraxial.FNO())
    spot = SpotDiagram(optic)
    geometric = _to_array(spot.geometric_spot_radius())
    rms = _to_array(spot.rms_spot_radius())
    opd = OPD(optic, (0, 0), optic.primary_wavelength)
    opd_rms = _to_float(opd.rms())
    psf_requested_num_rays = 128
    psf = FFTPSF(
        optic,
        (0, 0),
        optic.primary_wavelength,
        num_rays=psf_requested_num_rays,
        strategy="chief_ray",
        remove_tilt=False,
    )
    psf_array = np.asarray(be.to_numpy(psf.psf), dtype=float)
    strehl = float(psf.strehl_ratio())
    # A 64-ray MTF is sufficient for physical invariants and avoids repeating
    # the full 128-ray PSF cost already exercised immediately above.
    mtf_requested_num_rays = 64
    mtf = FFTMTF(
        optic,
        fields=[(0, 0)],
        wavelength=optic.primary_wavelength,
        num_rays=mtf_requested_num_rays,
        strategy="chief_ray",
        remove_tilt=False,
    )
    tangential = np.asarray(be.to_numpy(mtf.mtf[0][0]), dtype=float)
    sagittal = np.asarray(be.to_numpy(mtf.mtf[0][1]), dtype=float)
    freq_tang = np.asarray(be.to_numpy(mtf.freq_tang[0]), dtype=float)
    freq_sag = np.asarray(be.to_numpy(mtf.freq_sag[0]), dtype=float)
    result: dict[str, Any] = {
        "effective_focal_length_mm": efl,
        "f_number": fno,
        "spot": {
            "geometric_radius_mm": geometric.tolist() if full_arrays else None,
            "rms_radius_mm": rms.tolist() if full_arrays else None,
            "geometric_max_mm": float(np.max(geometric)),
            "rms_max_mm": float(np.max(rms)),
        },
        "wavefront": {
            "field_normalized": [0.0, 0.0],
            "wavelength_um": float(optic.primary_wavelength),
            "opd_rms_waves": opd_rms,
        },
        "psf": {
            "shape": list(psf_array.shape),
            "finite": bool(np.all(np.isfinite(psf_array))),
            "nonnegative": bool(np.min(psf_array) >= -1e-12),
            "strehl_ratio": strehl,
            "sampling": {
                "requested_num_rays": psf_requested_num_rays,
                "actual_pupil_samples_per_axis": int(psf.num_rays),
                "fft_grid_size_per_axis": int(psf.grid_size),
                "strategy": "chief_ray",
                "remove_tilt": bool(psf.remove_tilt),
            },
        },
        "mtf": {
            "samples": int(tangential.size),
            "tangential_dc": float(tangential[0]),
            "sagittal_dc": float(sagittal[0]),
            "finite": bool(np.all(np.isfinite(tangential)) and np.all(np.isfinite(sagittal))),
            "within_physical_bounds": bool(np.min(tangential) >= -1e-12 and np.max(tangential) <= 1 + 1e-12 and np.min(sagittal) >= -1e-12 and np.max(sagittal) <= 1 + 1e-12),
            "frequency_axes_increasing": bool(np.all(np.diff(freq_tang) > 0) and np.all(np.diff(freq_sag) > 0)),
            "frequency_max_cycles_per_mm": [float(freq_tang[-1]), float(freq_sag[-1])],
            "sampling": {
                "requested_num_rays": mtf_requested_num_rays,
                "actual_pupil_samples_per_axis": int(mtf.num_rays),
                "fft_grid_size_per_axis": int(mtf.grid_size),
                "strategy": "chief_ray",
                "remove_tilt": bool(mtf.remove_tilt),
            },
        },
    }
    return result


def _cooke_regression(package_manifest: dict[str, Any]) -> dict[str, Any]:
    lens = CookeTriplet()
    surface = _surface_summary(lens)
    metrics = _optical_metrics(lens, full_arrays=True)
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "installed_optiland_code_manifest",
            package_manifest["matches_pin"],
            {
                "sha256": package_manifest["sha256"],
                "file_count": package_manifest["file_count"],
            },
            {
                "sha256": package_manifest["expected_sha256"],
                "file_count": package_manifest["expected_file_count"],
            },
            "Hashes installed Optiland source-code files; generated caches are excluded",
        )
    )
    checks.append(_check("surface_count", surface["surface_count"] == 8, surface["surface_count"], 8))
    checks.append(_check("stop_surface", surface["stop_surfaces"] == [4], surface["stop_surfaces"], [4]))
    radius_ok = all(
        (math.isinf(actual) and math.isinf(expected)) or math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
        for actual, expected in zip(surface["radii_mm"], EXPECTED_RADII_MM, strict=True)
    )
    checks.append(_check("prescription_radii_mm", radius_ok, surface["radii_mm"], EXPECTED_RADII_MM))
    actual_thickness = surface["thickness_mm"][: len(EXPECTED_THICKNESS_MM)]
    thickness_ok = all(
        (math.isinf(actual) and math.isinf(expected)) or math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
        for actual, expected in zip(actual_thickness, EXPECTED_THICKNESS_MM, strict=True)
    )
    checks.append(_check("prescription_thickness_mm", thickness_ok, actual_thickness, EXPECTED_THICKNESS_MM))

    efl = metrics["effective_focal_length_mm"]
    fno = metrics["f_number"]
    checks.append(_check("effective_focal_length_mm", np.isclose(efl, EXPECTED_EFL_MM, rtol=RTOL, atol=ATOL), efl, EXPECTED_EFL_MM))
    checks.append(_check("f_number", np.isclose(fno, EXPECTED_FNO, rtol=RTOL, atol=ATOL), fno, EXPECTED_FNO))
    geometric = np.asarray(metrics["spot"]["geometric_radius_mm"])
    rms = np.asarray(metrics["spot"]["rms_radius_mm"])
    checks.append(_check("geometric_spot_radius_mm", np.allclose(geometric, EXPECTED_GEOMETRIC_MM, rtol=RTOL, atol=ATOL), geometric.tolist(), EXPECTED_GEOMETRIC_MM.tolist()))
    checks.append(_check("rms_spot_radius_mm", np.allclose(rms, EXPECTED_RMS_MM, rtol=RTOL, atol=ATOL), rms.tolist(), EXPECTED_RMS_MM.tolist()))

    opd_max = OPD(lens, (0, 1), 0.55)
    opd_max_rms = _to_float(opd_max.rms())
    checks.append(_check("opd_rms_max_field_waves", np.isclose(opd_max_rms, EXPECTED_OPD_RMS_WAVES, rtol=RTOL, atol=ATOL), opd_max_rms, EXPECTED_OPD_RMS_WAVES))
    metrics["wavefront_max_field"] = {"field_normalized": [0.0, 1.0], "wavelength_um": 0.55, "opd_rms_waves": opd_max_rms}

    psf = metrics["psf"]
    checks.append(_check("psf_shape", psf["shape"] == [256, 256], psf["shape"], [256, 256]))
    checks.append(_check("psf_physical", psf["finite"] and psf["nonnegative"], {"finite": psf["finite"], "nonnegative": psf["nonnegative"]}, {"finite": True, "nonnegative": True}))
    checks.append(_check("strehl_ratio", np.isclose(psf["strehl_ratio"], EXPECTED_STREHL, rtol=5e-4, atol=1e-7), psf["strehl_ratio"], EXPECTED_STREHL, "Windows NumPy/JIT-disabled baseline at default FFT sampling; upstream tests require only [0,1]"))
    mtf = metrics["mtf"]
    mtf_ok = mtf["finite"] and mtf["within_physical_bounds"] and mtf["frequency_axes_increasing"] and np.isclose(mtf["tangential_dc"], 1.0, atol=1e-12) and np.isclose(mtf["sagittal_dc"], 1.0, atol=1e-12)
    checks.append(_check("mtf_physical", mtf_ok, mtf, "finite; DC=1; values in [0,1]; increasing frequency axes"))

    nominal_radius = _to_float(lens.surfaces[1].geometry.radius)
    tolerancing = Tolerancing(lens)
    tolerancing.add_operand("f2", input_data={"optic": lens})
    tolerancing.add_perturbation("radius", RangeSampler(nominal_radius - 0.01, nominal_radius + 0.01, 3), surface_number=1)
    sensitivity = SensitivityAnalysis(tolerancing)
    sensitivity.run()
    frame = sensitivity.get_results()
    restored_radius = _to_float(lens.surfaces[1].geometry.radius)
    numeric = frame.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    tolerance_ok = len(frame) == 3 and numeric.size > 0 and np.all(np.isfinite(numeric)) and np.isclose(restored_radius, nominal_radius, rtol=0, atol=1e-12)
    checks.append(_check("three_point_sensitivity_and_reset", tolerance_ok, {"rows": len(frame), "finite": bool(np.all(np.isfinite(numeric))), "nominal_radius_mm": nominal_radius, "restored_radius_mm": restored_radius}, {"rows": 3, "finite": True, "restored": True}, "Deterministic sensitivity only; not a yield Monte Carlo"))

    group_ranges = ((1, 2), (3, 4), (5, 6), (1, 6))
    group_results: dict[str, Any] = {}
    for start, end in group_ranges:
        matrix = np.asarray(
            be.to_numpy(lens.paraxial.ray_transfer_matrix(start, end)), dtype=float
        )
        group_results[f"{start}-{end}"] = {
            "f2_mm": _to_float(lens.paraxial.f2_range(start, end)),
            "ABCD": matrix.tolist(),
            "determinant": float(np.linalg.det(matrix)),
        }
    positions = np.asarray(be.to_numpy(be.ravel(lens.surfaces.positions)), dtype=float)
    first = np.asarray(group_results["1-3"]["ABCD"], dtype=float) if "1-3" in group_results else np.asarray(be.to_numpy(lens.paraxial.ray_transfer_matrix(1, 3)), dtype=float)
    second = np.asarray(be.to_numpy(lens.paraxial.ray_transfer_matrix(4, 6)), dtype=float)
    transfer = np.asarray([[1.0, positions[4] - positions[3]], [0.0, 1.0]])
    composed = second @ transfer @ first
    whole = np.asarray(group_results["1-6"]["ABCD"], dtype=float)
    group_power = sum(1.0 / group_results[key]["f2_mm"] for key in ("1-2", "3-4", "5-6"))
    system_power = 1.0 / group_results["1-6"]["f2_mm"]
    group_ok = (
        np.allclose(composed, whole, rtol=1e-12, atol=1e-12)
        and all(
            math.isclose(item["determinant"], 1.0, rel_tol=1e-12, abs_tol=1e-12)
            for item in group_results.values()
        )
        and math.isclose(
            group_results["1-6"]["f2_mm"], efl, rel_tol=1e-12, abs_tol=0.0
        )
        and abs(group_power - system_power) > 1e-3
    )
    checks.append(
        _check(
            "cooke_surface_group_efl_and_abcd",
            group_ok,
            {
                "groups": group_results,
                "composed_1_6_ABCD": composed.tolist(),
                "group_power_per_mm": group_power,
                "system_power_per_mm": system_power,
            },
            "ABCD composition and determinant pass at 1e-12; full-range EFL equals system EFL; isolated group powers are not added as system power",
            "Surface-range EFLs describe isolated groups and are not a decomposition of total system power",
        )
    )

    external_hubble = HubbleTelescope()
    external_first_order: dict[str, Any] = {}
    external_first_order_ok = True
    for quantity, (expected, tolerance) in HUBBLE_FIRST_ORDER_OPTICSTUDIO_2023.items():
        actual = _to_float(getattr(external_hubble.paraxial, quantity)())
        passed = math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)
        external_first_order_ok = external_first_order_ok and passed
        external_first_order[quantity] = {
            "actual": actual,
            "expected": expected,
            "absolute_tolerance": tolerance,
            "passed": passed,
        }
    external_rays: list[dict[str, Any]] = []
    external_rays_ok = True
    for pupil_field, expected in HUBBLE_RAYS_OPTICSTUDIO_2023:
        actual = _image_intercept(external_hubble, *pupil_field, 0.55)
        max_abs_error = max(
            abs(got - want) for got, want in zip(actual, expected, strict=True)
        )
        external_rays_ok = external_rays_ok and max_abs_error <= 1e-6
        external_rays.append(
            {
                "field_pupil": list(pupil_field),
                "actual_xyLM": list(actual),
                "expected_xyLM": list(expected),
                "max_abs_error": max_abs_error,
            }
        )
    external_spot = SpotDiagram(
        external_hubble, fields="all", wavelengths=[0.55]
    )
    external_rms = _to_array(external_spot.rms_spot_radius())
    external_geo = _to_array(external_spot.geometric_spot_radius())
    external_spot_rows: list[dict[str, Any]] = []
    external_spot_ok = True
    for field_index, (expected_rms, expected_geo) in HUBBLE_SPOT_OPTICSTUDIO_2023_MM.items():
        actual_rms = float(external_rms[field_index][0])
        actual_geo = float(external_geo[field_index][0])
        passed = math.isclose(actual_rms, expected_rms, rel_tol=1e-2) and math.isclose(
            actual_geo, expected_geo, rel_tol=1e-2
        )
        external_spot_ok = external_spot_ok and passed
        external_spot_rows.append(
            {
                "field_index": field_index,
                "actual_rms_mm": actual_rms,
                "expected_rms_mm": expected_rms,
                "actual_geometric_mm": actual_geo,
                "expected_geometric_mm": expected_geo,
                "passed": passed,
            }
        )
    checks.append(
        _check(
            "hubble_independent_opticstudio_2023_reference",
            external_first_order_ok and external_rays_ok and external_spot_ok,
            {
                "first_order": external_first_order,
                "real_rays": external_rays,
                "spot": external_spot_rows,
            },
            {
                "first_order": "published-value-specific absolute tolerances",
                "real_ray_xyLM_atol": 1e-6,
                "spot_relative_tolerance": 1e-2,
            },
            "Independent constants from OpticStudio 2023 R1.02 in Optiland test_cross_tool_validation.py; never regenerate them from Optiland",
        )
    )
    checks.append(
        _check(
            "hubble_rms_wavefront_sampling_convergence",
            False,
            "hexapolar RMS reduction remains O(1/N); Hubble extrapolation leaves 0.00076 waves unexplained",
            "successive ring counts converge before a fixed-value regression is accepted",
            "Known upstream issue #710; retained as evidence and deliberately excluded from acceptance",
            required_for_acceptance=False,
        )
    )
    checks.append(
        _check(
            "hubble_tangential_field_curvature_external_reference",
            False,
            -1.67515169,
            -1.66509538,
            "Known strict xfail from upstream cross-tool validation: 0.6% tangential focus-shift discrepancy; do not loosen the 1e-6 mm comparison",
            required_for_acceptance=False,
        )
    )

    with tempfile.TemporaryDirectory(prefix="optiland-regression-") as temp_dir:
        temp = Path(temp_dir)
        json_path = temp / "cooke.optiland.json"
        save_optiland_file(lens, str(json_path))
        json_loaded = load_optiland_file(str(json_path))
        json_equal = lens.to_dict() == json_loaded.to_dict()
        checks.append(_check("optiland_json_roundtrip", json_equal, json_equal, True))

        precision_rays = [
            (0.0, 0.0, 0.0, 0.7),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.7, 0.7, 0.0),
        ]
        for sample_name, sample in (
            ("hubble", HubbleTelescope()),
            ("double_gauss", DoubleGauss()),
        ):
            zmx_path = temp / f"{sample_name}.zmx"
            save_zemax_file(sample, str(zmx_path))
            loaded = load_zemax_file(str(zmx_path))
            paraxial: dict[str, Any] = {}
            paraxial_ok = True
            for quantity in ("f2", "EPD", "FNO", "EPL", "XPD"):
                before_value = _to_float(getattr(sample.paraxial, quantity)())
                after_value = _to_float(getattr(loaded.paraxial, quantity)())
                paraxial[quantity] = {
                    "before": before_value,
                    "after": after_value,
                    "relative_error": abs(after_value - before_value)
                    / max(abs(before_value), np.finfo(float).tiny),
                }
                paraxial_ok = paraxial_ok and math.isclose(
                    before_value, after_value, rel_tol=1e-12, abs_tol=0.0
                )

            ray_results: list[dict[str, Any]] = []
            rays_ok = True
            for hx, hy, px, py in precision_rays:
                before_ray = _image_intercept(
                    sample, hx, hy, px, py, sample.primary_wavelength
                )
                after_ray = _image_intercept(
                    loaded, hx, hy, px, py, sample.primary_wavelength
                )
                max_abs_error = max(
                    abs(before - after)
                    for before, after in zip(before_ray, after_ray, strict=True)
                )
                rays_ok = rays_ok and max_abs_error <= 1e-9
                ray_results.append(
                    {
                        "field": [hx, hy],
                        "pupil": [px, py],
                        "before_xyLM": list(before_ray),
                        "after_xyLM": list(after_ray),
                        "max_abs_error": max_abs_error,
                    }
                )

            mirror_count = sum(
                1
                for surface in loaded.surfaces
                if bool(surface.interaction_model.is_reflective)
            )
            mirrors_ok = sample_name != "hubble" or mirror_count == 2
            checks.append(
                _check(
                    f"{sample_name}_zmx_float64_roundtrip",
                    paraxial_ok and rays_ok and mirrors_ok,
                    {
                        "paraxial": paraxial,
                        "real_rays": ray_results,
                        "reloaded_mirror_count": mirror_count,
                        "first_bytes_hex": zmx_path.read_bytes()[:4].hex(),
                    },
                    {
                        "paraxial_rtol": 1e-12,
                        "real_ray_xyLM_atol": 1e-9,
                        "hubble_mirror_count": 2,
                    },
                    "Strict in-memory to ZMX to Optiland round-trip; external OpticStudio comparison is separate",
                )
            )

        from optiland.fileio.zemax.writer.encoder import _fmt

        formatter_values = [
            9.05795225862422e-05,
            -11040.02286,
            1.0 / 3.0,
            6365.20955,
        ]
        formatter_roundtrips = [float(_fmt(value)) == value for value in formatter_values]
        checks.append(
            _check(
                "zmx_float_formatter_binary64_roundtrip",
                all(formatter_roundtrips),
                {
                    "values": formatter_values,
                    "formatted": [_fmt(value) for value in formatter_values],
                    "exact_roundtrip": formatter_roundtrips,
                },
                "all values recover their exact Python float",
            )
        )

        cooke_zmx = temp / "cooke.zmx"
        save_zemax_file(lens, str(cooke_zmx))
        cooke_loaded = load_zemax_file(str(cooke_zmx))
        cooke_efl_before = _to_float(lens.paraxial.f2())
        cooke_efl_after = _to_float(cooke_loaded.paraxial.f2())
        cooke_materials_before = _material_signature(lens)
        cooke_materials_after = _material_signature(cooke_loaded)
        cooke_catalog_ok = cooke_materials_before == cooke_materials_after
        cooke_efl_ok = math.isclose(
            cooke_efl_before, cooke_efl_after, rel_tol=1e-12, abs_tol=0.0
        )
        checks.append(
            _check(
                "cooke_zmx_glass_catalog_fidelity",
                cooke_catalog_ok and cooke_efl_ok,
                {
                    "materials_before": cooke_materials_before,
                    "materials_after": cooke_materials_after,
                    "efl_before_mm": cooke_efl_before,
                    "efl_after_mm": cooke_efl_after,
                    "efl_relative_error": abs(cooke_efl_after - cooke_efl_before)
                    / abs(cooke_efl_before),
                },
                "catalog identity, actual n(lambda), and EFL preserved at 1e-12 relative tolerance",
                "The writer now emits Nd/Vd and the reader uses them to disambiguate names inside declared GCAT catalogs; third-party import semantics remain an external check",
            )
        )

    return {"surface": surface, "metrics": metrics, "tolerance": {"rows": frame.to_dict(orient="records")}, "checks": checks}


def _generic_zmx(path: Path) -> dict[str, Any]:
    before = _sha256(path)
    optic = load_zemax_file(str(path))
    surface = _surface_summary(optic)
    metrics = _optical_metrics(optic, full_arrays=True)
    after = _sha256(path)
    if before != after:
        raise RegressionError("source ZMX changed during read-only analysis")
    spot_geometric = np.asarray(metrics["spot"]["geometric_radius_mm"], dtype=float)
    spot_rms = np.asarray(metrics["spot"]["rms_radius_mm"], dtype=float)
    psf = metrics["psf"]
    mtf = metrics["mtf"]
    checks = [
        _check("source_unchanged", before == after, after, before),
        _check(
            "prescription_loaded",
            surface["surface_count"] >= 2,
            surface["surface_count"],
            "at least 2 surfaces",
        ),
        _check(
            "paraxial_metrics_finite",
            math.isfinite(metrics["effective_focal_length_mm"])
            and math.isfinite(metrics["f_number"]),
            {
                "effective_focal_length_mm": metrics["effective_focal_length_mm"],
                "f_number": metrics["f_number"],
            },
            "finite EFL and F/#",
        ),
        _check(
            "spot_metrics_physical",
            spot_geometric.size > 0
            and spot_rms.size > 0
            and np.all(np.isfinite(spot_geometric))
            and np.all(np.isfinite(spot_rms))
            and np.all(spot_geometric >= 0)
            and np.all(spot_rms >= 0),
            {
                "geometric_shape": list(spot_geometric.shape),
                "rms_shape": list(spot_rms.shape),
                "geometric_max_mm": metrics["spot"]["geometric_max_mm"],
                "rms_max_mm": metrics["spot"]["rms_max_mm"],
            },
            "finite, non-negative, non-empty spot arrays",
        ),
        _check(
            "wavefront_metric_finite",
            math.isfinite(metrics["wavefront"]["opd_rms_waves"]),
            metrics["wavefront"],
            "finite OPD RMS",
        ),
        _check(
            "psf_physical",
            len(psf["shape"]) == 2
            and min(psf["shape"]) > 0
            and psf["finite"]
            and psf["nonnegative"]
            and math.isfinite(psf["strehl_ratio"])
            and 0 <= psf["strehl_ratio"] <= 1,
            psf,
            "non-empty finite non-negative 2-D PSF and Strehl in [0,1]",
        ),
        _check(
            "mtf_physical",
            mtf["samples"] > 1
            and mtf["finite"]
            and mtf["within_physical_bounds"]
            and mtf["frequency_axes_increasing"]
            and np.isclose(mtf["tangential_dc"], 1.0, atol=1e-12)
            and np.isclose(mtf["sagittal_dc"], 1.0, atol=1e-12),
            mtf,
            "finite; DC=1; values in [0,1]; increasing frequency axes",
        ),
    ]
    return {
        "source": {"path": str(path), "sha256_before": before, "sha256_after": after, "unchanged": True},
        "surface": surface,
        "metrics": metrics,
        "checks": checks,
    }


def _base_report(mode: str, package_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": mode,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "software": {
            "optiland_version": _version("optiland"),
            "optiland_source_commit": PINNED_SHA,
            "optiland_installed_code_manifest": package_manifest,
            "numpy": np.__version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "backend": "numpy",
            "numba_disable_jit": True,
            "matplotlib_config": "ephemeral_temp_directory",
        },
        "units": {"length": "mm", "wavelength": "um", "opd_rms": "waves", "spatial_frequency": "cycles/mm"},
        "limitations": [
            "Synthetic/reference models are not measured acceptance data",
            "Optiland ZMX self-roundtrip does not prove Ansys Zemax OpticStudio compatibility",
            "ZMX encoding and feature semantics still require validation in the target OpticStudio version",
            "Nd/Vd-assisted catalog disambiguation is qualified for the Cooke sample only; it is not a guarantee for every third-party catalog/importer",
            "Independent Hubble references come from OpticStudio 2023 R1.02; local versioned-copy terminal review uses OpticStudio 2022 R2.02 and is recorded separately",
            "Hubble RMS wavefront sampling convergence and tangential field-curvature discrepancy remain unresolved non-blocking findings",
            "No non-sequential stray-light, ghost, coating-manufacturing, or optomechanical analysis",
            "Sensitivity sweep is not tolerance yield or manufacturing Monte Carlo",
            "JIT-enabled Optiland import timed out on the Windows qualification host and is not qualified; all reported baselines use process-local NUMBA_DISABLE_JIT=1",
        ],
    }


def _atomic_json(
    path: Path,
    payload: dict[str, Any],
    force: bool,
    protected_paths: set[Path] | None = None,
) -> None:
    target = path.expanduser().resolve(strict=False)
    if target.suffix.lower() != ".json":
        raise RegressionError("report output must use a .json suffix")
    for protected in protected_paths or set():
        if target == protected or (
            target.exists() and protected.exists() and os.path.samefile(target, protected)
        ):
            raise RegressionError(f"report output must not replace an input: {protected}")
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(_json_safe(payload), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _json_safe(value: Any) -> Any:
    """Convert backend/numeric values to strict JSON without hiding infinity."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-test", action="store_true", help="run the pinned Cooke/Hubble regression")
    modes.add_argument("--input-zmx", help="analyze one local ZMX prescription without modifying it")
    parser.add_argument("--output", help="new JSON report path")
    parser.add_argument("--force", action="store_true", help="replace an existing report only when explicitly authorized")
    args = parser.parse_args()

    package_manifest = _package_code_manifest()

    if args.self_test:
        report = _base_report("synthetic_reference_self_test", package_manifest)
        report["data_class"] = "synthetic_reference_not_measurement"
        report["regression"] = _cooke_regression(package_manifest)
        failed = [
            check["name"]
            for check in report["regression"]["checks"]
            if not check["passed"] and check.get("required_for_acceptance", True)
        ]
        report["nonblocking_findings"] = [
            check["name"]
            for check in report["regression"]["checks"]
            if not check["passed"] and not check.get("required_for_acceptance", True)
        ]
        report["status"] = "PASS" if not failed else "FAIL"
        report["failed_checks"] = failed
        protected_paths: set[Path] = set()
    else:
        source = _local_input(args.input_zmx)
        report = _base_report("local_zmx_read_only_analysis", package_manifest)
        report["qualification"] = _cooke_regression(package_manifest)
        qualification_failed = [
            check["name"]
            for check in report["qualification"]["checks"]
            if not check["passed"] and check.get("required_for_acceptance", True)
        ]
        report["nonblocking_findings"] = [
            check["name"]
            for check in report["qualification"]["checks"]
            if not check["passed"] and not check.get("required_for_acceptance", True)
        ]
        if qualification_failed:
            report["analysis"] = {
                "status": "SKIPPED",
                "reason": "pinned Cooke/runtime qualification failed",
            }
            failed = [f"qualification:{name}" for name in qualification_failed]
        else:
            report["analysis"] = _generic_zmx(source)
            analysis_failed = [
                check["name"]
                for check in report["analysis"]["checks"]
                if not check["passed"]
            ]
            failed = [f"analysis:{name}" for name in analysis_failed]
        report["status"] = "PASS" if not failed else "FAIL"
        report["failed_checks"] = failed
        protected_paths = {source}

    if args.output:
        _atomic_json(Path(args.output), report, args.force, protected_paths)
    print(json.dumps({"status": report["status"], "mode": report["mode"], "failed_checks": report.get("failed_checks", []), "output": str(Path(args.output).resolve()) if args.output else None}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RegressionError, FileExistsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
