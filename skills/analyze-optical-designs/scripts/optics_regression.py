#!/usr/bin/env python3
"""Deterministic smoke and regression checks for the pinned optics runtime."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any

import jax
import jax.numpy as jnp
import numpy as np

import chromatix.functional as cx
from prysm.otf import mtf_from_psf
from prysm.propagation.fft import focus


EXPECTED_COMMITS = {
    "chromatix": "ce1482906fc663298613bb252bbf425e3be59839",
    "prysm": "5008f47803af6ff69eed474fca049456076e4a7d",
}
FREEZE_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"
# Test tooling may share the environment; it is reported but never counts as drift.
TEST_TOOLING = {"pytest", "iniconfig", "pluggy", "pygments", "colorama"}


def canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def direct_url_commit(distribution: str) -> str | None:
    dist = importlib.metadata.distribution(distribution)
    direct_url = dist.read_text("direct_url.json")
    if direct_url is None:
        return None
    data = json.loads(direct_url)
    return data.get("vcs_info", {}).get("commit_id")


def chromatix_check() -> dict[str, Any]:
    # Float64 for this check only: in float32 the power sum (also used by
    # plane_wave to normalize) depends on the CPU's reduction order by up to
    # ~1e-5, which would make the 1e-6 normalization test machine-dependent.
    with jax.enable_x64(True):
        field = cx.plane_wave(
            shape=(32, 32),
            dx=1.0e-6,
            spectrum=532.0e-9,
            power=1.0,
        )
        focused = cx.ff_lens(field, f=10.0e-3, n=1.0)
        dtype = str(np.asarray(field.u).dtype)
        input_power = float(np.asarray(field.power).squeeze())
        output_power = float(np.asarray(focused.power).squeeze())
        finite = bool(np.isfinite(np.asarray(focused.intensity)).all())
    relative_power_error = abs(output_power - input_power) / input_power
    passed = (
        finite
        and math.isclose(input_power, 1.0, rel_tol=1e-6, abs_tol=1e-6)
        and relative_power_error < 1e-5
    )
    return {
        "passed": passed,
        "input_power": input_power,
        "output_power": output_power,
        "relative_power_error": relative_power_error,
        "finite_intensity": finite,
        "dtype": dtype,
    }


def prysm_check() -> dict[str, Any]:
    axis = np.linspace(-1.0, 1.0, 64, endpoint=False)
    x, y = np.meshgrid(axis, axis)
    pupil = (x * x + y * y <= 0.70**2).astype(np.complex128)
    focused = focus(pupil, Q=2)
    input_energy = float(np.sum(np.abs(pupil) ** 2))
    output_energy = float(np.sum(np.abs(focused) ** 2))
    psf = np.abs(focused) ** 2
    psf /= psf.sum()
    mtf = mtf_from_psf(psf, dx=1.0)
    cy, cx_index = (v // 2 for v in mtf.data.shape)
    mtf_center = float(mtf.data[cy, cx_index])
    relative_energy_error = abs(output_energy - input_energy) / input_energy
    passed = relative_energy_error < 1e-12 and math.isclose(
        mtf_center, 1.0, rel_tol=1e-12, abs_tol=1e-12
    )
    return {
        "passed": passed,
        "input_energy": input_energy,
        "output_energy": output_energy,
        "relative_energy_error": relative_energy_error,
        "mtf_center": mtf_center,
    }


def chromatix_gradient_check() -> dict[str, Any]:
    field = cx.plane_wave(
        shape=(64, 64),
        dx=1.0e-6,
        spectrum=532.0e-9,
        power=1.0,
    )
    axis = (np.arange(64) - 31.5) / 32.0
    x, y = np.meshgrid(axis, axis)
    r2 = jnp.asarray(x * x + y * y)

    def center_fraction(defocus: float) -> jax.Array:
        focused = cx.ff_lens(cx.phase_change(field, defocus * r2), f=10.0e-3, n=1.0)
        intensity = jnp.squeeze(focused.intensity)
        return intensity[32, 32] / jnp.sum(intensity)

    defocus, step = 0.7, 1.0e-2
    gradient = float(jax.grad(center_fraction)(defocus))
    finite_difference = float(
        (center_fraction(defocus + step) - center_fraction(defocus - step)) / (2.0 * step)
    )
    relative_error = abs(gradient - finite_difference) / abs(finite_difference)
    passed = math.isfinite(gradient) and gradient != 0.0 and relative_error < 1e-3
    return {
        "passed": passed,
        "gradient": gradient,
        "finite_difference": finite_difference,
        "relative_error": relative_error,
    }


def prysm_analytic_mtf_check() -> dict[str, Any]:
    radius = 32
    axis = np.arange(128) - 63.5
    x, y = np.meshgrid(axis, axis)
    pupil = (x * x + y * y <= radius * radius).astype(np.complex128)
    psf = np.abs(focus(pupil, Q=2)) ** 2
    psf /= psf.sum()
    mtf = mtf_from_psf(psf, dx=1.0).data
    cy, cx_index = (v // 2 for v in mtf.shape)
    errors = {}
    for nu in (0.25, 0.5, 0.75):
        phi = math.acos(nu)
        analytic = (2.0 / math.pi) * (phi - math.cos(phi) * math.sin(phi))
        sampled = float(mtf[cy, cx_index + round(nu * 2 * radius)])
        errors[str(nu)] = abs(sampled - analytic)
    max_error = max(errors.values())
    return {
        "passed": max_error < 2e-3,
        "absolute_errors": errors,
        "max_absolute_error": max_error,
    }


def freeze_check() -> dict[str, Any]:
    expected = {}
    for line in FREEZE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " @ " in line:
            name, url = line.split(" @ ", 1)
            expected[canonical(name)] = url.rsplit("@", 1)[1]
        else:
            name, version = line.split("==", 1)
            expected[canonical(name)] = version
    installed = {}
    for dist in importlib.metadata.distributions():
        name = canonical(dist.metadata["Name"])
        if name == "pip":
            continue
        installed[name] = direct_url_commit(dist.metadata["Name"]) or dist.version
    missing = sorted(set(expected) - set(installed))
    tooling = sorted(TEST_TOOLING & (set(installed) - set(expected)))
    extra = sorted(set(installed) - set(expected) - TEST_TOOLING)
    mismatched = {
        name: {"expected": expected[name], "installed": installed[name]}
        for name in sorted(set(expected) & set(installed))
        if expected[name] != installed[name]
    }
    return {
        "passed": not (missing or extra or mismatched),
        "freeze_path": str(FREEZE_PATH),
        "distribution_count": len(installed),
        "missing": missing,
        "extra": extra,
        "ignored_test_tooling": tooling,
        "mismatched": mismatched,
    }


def provenance() -> dict[str, Any]:
    packages = {}
    for name in ("chromatix", "prysm", "jax", "jaxlib", "numpy", "scipy"):
        packages[name] = importlib.metadata.version(name)
    commits = {name: direct_url_commit(name) for name in EXPECTED_COMMITS}
    pins_match = all(commits[name] == expected for name, expected in EXPECTED_COMMITS.items())
    return {
        "packages": packages,
        "commits": commits,
        "expected_commits": EXPECTED_COMMITS,
        "pins_match": pins_match,
        "jax_backend": jax.default_backend(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = {
        "provenance": provenance(),
        "chromatix": chromatix_check(),
        "prysm": prysm_check(),
        "chromatix_gradient": chromatix_gradient_check(),
        "prysm_analytic_mtf": prysm_analytic_mtf_check(),
        "freeze": freeze_check(),
    }
    result["passed"] = bool(
        result["provenance"]["pins_match"]
        and all(
            result[key]["passed"]
            for key in ("chromatix", "prysm", "chromatix_gradient", "prysm_analytic_mtf", "freeze")
        )
    )

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.self_test and not result["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
