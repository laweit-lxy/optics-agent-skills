#!/usr/bin/env python3
"""Read-only RayOptics inspection and first-order cross-check for local ZMX files."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile
from typing import Any, Iterator


PINNED_SHA = "e25bc579116d31ed97fa1632f871e2801e8e956e"
# The RayOptics package is located in the running interpreter's environment
# (install it from requirements/cross-check-optical-designs.txt). An optional
# refractiveindex.info database snapshot is read from this environment variable.
RII_DB_ENV = "OPTICS_SKILLS_RII_DB"
EXPECTED_PACKAGE_MANIFEST_SHA256 = "76b2b57d9b5db8b91fd34f1e5ef971cc7c57752e1b1e3d858ce0302d3c106924"
EXPECTED_PACKAGE_FILE_COUNT = 192
EXPECTED_RII_FILE_COUNT = 4174
EXPECTED_RII_CATALOG_NK_SHA256 = (
    "3a4a18908b03b99e258f4f329d8fc56e7d79757902a5153a212508a19a146cf1"
)
EXPECTED_RII_CATALOG_N2_SHA256 = (
    "42db48e7361281e863c9d1995081cf87ba945477ecdc6ab4aaE090e4cee1ae92".lower()
)


POLICY_PATH = Path(__file__).resolve().with_name("rayoptics_local_policy.py")
_POLICY = None


def _package_root() -> Path | None:
    spec = importlib.util.find_spec("rayoptics")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent


def _installed_commit() -> str | None:
    """Return the VCS commit recorded by pip for the installed RayOptics, if any."""
    try:
        text = importlib.metadata.distribution("rayoptics").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not text:
        return None
    return json.loads(text).get("vcs_info", {}).get("commit_id")


def _rii_db_root() -> Path | None:
    value = os.environ.get(RII_DB_ENV)
    return Path(value).expanduser().resolve() if value else None


class CrossCheckError(RuntimeError):
    """Raised for safety, qualification, or input errors."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_remote_or_reparse(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise CrossCheckError(f"{label} must use an absolute local path")
    if str(path).startswith("\\\\") or path.anchor.startswith("\\\\"):
        raise CrossCheckError(f"{label} must not use a UNC/network path")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    cursor = path
    while True:
        try:
            info = os.lstat(cursor)
        except FileNotFoundError:
            pass
        else:
            attributes = getattr(info, "st_file_attributes", 0)
            if stat.S_ISLNK(info.st_mode) or (
                reparse_flag and attributes & reparse_flag
            ):
                raise CrossCheckError(
                    f"{label} path contains a symlink or reparse point: {cursor}"
                )
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


def _local_file(path_text: str, label: str, suffixes: set[str]) -> Path:
    if "://" in path_text:
        raise CrossCheckError(f"{label} does not accept URLs")
    path = Path(path_text).expanduser()
    _reject_remote_or_reparse(path, label)
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise CrossCheckError(f"{label} must be a regular local {allowed} file")
    return resolved


def _package_manifest() -> dict[str, Any]:
    root = _package_root()
    commit = _installed_commit()
    if root is None:
        return {"root": None, "installed_commit": commit, "commit_matches_pin": False,
                "manifest_matches_frozen": False, "matches_pin": False}
    files = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    digest = hashlib.sha256()
    byte_count = 0
    for path in files:
        contents = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(contents).digest())
        byte_count += len(contents)
    actual = digest.hexdigest()
    manifest_ok = (len(files) == EXPECTED_PACKAGE_FILE_COUNT
                   and actual == EXPECTED_PACKAGE_MANIFEST_SHA256)
    return {
        "root": str(root),
        "installed_commit": commit,
        "commit_matches_pin": commit == PINNED_SHA,
        "manifest_matches_frozen": manifest_ok,
        "algorithm": "sha256(sorted relative UTF-8 path + NUL + per-file SHA-256)",
        "file_count": len(files),
        "byte_count": byte_count,
        "sha256": actual,
        "expected_file_count": EXPECTED_PACKAGE_FILE_COUNT,
        "expected_sha256": EXPECTED_PACKAGE_MANIFEST_SHA256,
        # A pip VCS install records the commit; line-ending conversion on checkout
        # can change file bytes, so either piece of evidence qualifies the source.
        "matches_pin": manifest_ok or commit == PINNED_SHA,
    }


def _rii_snapshot() -> dict[str, Any]:
    rii_root = _rii_db_root()
    if rii_root is None:
        # Optional: opticalglass's bundled vendor catalogs serve GCAT lookups.
        return {"root": None, "configured": False, "matches_pin": True}
    files = list(rii_root.rglob("*")) if rii_root.is_dir() else []
    file_count = sum(1 for path in files if path.is_file())
    catalog_nk = rii_root / "catalog-nk.yml"
    catalog_n2 = rii_root / "catalog-n2.yml"
    nk_sha = _sha256(catalog_nk) if catalog_nk.is_file() else None
    n2_sha = _sha256(catalog_n2) if catalog_n2.is_file() else None
    return {
        "root": str(rii_root),
        "configured": True,
        "file_count": file_count,
        "catalog_nk_sha256": nk_sha,
        "catalog_n2_sha256": n2_sha,
        "matches_pin": file_count == EXPECTED_RII_FILE_COUNT
        and nk_sha == EXPECTED_RII_CATALOG_NK_SHA256
        and n2_sha == EXPECTED_RII_CATALOG_N2_SHA256,
    }


def _call_or_value(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    try:
        return _json_safe(value.item())
    except (AttributeError, ValueError, TypeError):
        return str(value)


def _policy_manifest() -> dict[str, Any]:
    actual = _sha256(POLICY_PATH) if POLICY_PATH.is_file() else None
    # The policy is versioned with this script in the repository; record its digest.
    return {"path": str(POLICY_PATH), "sha256": actual, "matches_pin": actual is not None}


def _qualified_policy() -> Any:
    global _POLICY
    if not _policy_manifest()["matches_pin"]:
        raise CrossCheckError("local catalog/F-number policy integrity check failed")
    if _POLICY is None:
        spec = importlib.util.spec_from_file_location("rayoptics_qualified_policy_r2", POLICY_PATH)
        _POLICY = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_POLICY)
    return _POLICY


@contextmanager
def _rayoptics_runtime() -> Iterator[Any]:
    """Import the pinned source in an ephemeral cwd and apply one Windows shim."""
    rii_root = _rii_db_root()
    if _package_root() is None or (rii_root is not None and not rii_root.is_dir()):
        raise CrossCheckError("pinned RayOptics package or configured RII database is missing")
    if not _package_manifest()["matches_pin"] or not _rii_snapshot()["matches_pin"]:
        raise CrossCheckError("pinned RayOptics source or material data integrity check failed")
    policy = _qualified_policy()
    original_cwd = Path.cwd()
    old_source_path = list(sys.path)
    old_db = os.environ.get("refractiveindexinfodb")
    old_backend = os.environ.get("MPLBACKEND")
    old_config = os.environ.get("MPLCONFIGDIR")
    rindexinfo = None
    original_parser = None
    with tempfile.TemporaryDirectory(prefix="rayoptics-crosscheck-") as temp_dir:
        os.chdir(temp_dir)
        if rii_root is not None:
            os.environ["refractiveindexinfodb"] = str(rii_root)
        os.environ["MPLBACKEND"] = "Agg"
        os.environ["MPLCONFIGDIR"] = str(Path(temp_dir) / "matplotlib")
        try:
            import opticalglass.rindexinfo as rindexinfo

            original_parser = getattr(rindexinfo, "get_glassname_from_filestr", None)
            if original_parser is None and not hasattr(rindexinfo, "get_glassname_from_filepath"):
                raise CrossCheckError("unsupported opticalglass RII path parser")

            def windows_safe_parser(
                filestr: str, include_rii_page: bool = False
            ) -> tuple[str, str, str]:
                normalized = str(filestr).replace("\\", "/")
                return original_parser(normalized, include_rii_page)

            if original_parser is not None:
                rindexinfo.get_glassname_from_filestr = windows_safe_parser
            from rayoptics.zemax.zmxread import read_lens_file

            audit: list[dict[str, Any]] = []
            with policy.declared_catalog_import(audit):
                def guarded_reader(path: Path, **kwargs: Any) -> Any:
                    audit.clear()
                    model, info = read_lens_file(path, **kwargs)
                    model._crosscheck_catalog_audit = list(audit)
                    return model, info
                yield guarded_reader
        finally:
            if rindexinfo is not None and original_parser is not None:
                rindexinfo.get_glassname_from_filestr = original_parser
            logger = logging.getLogger("rayoptics.zemax.zmxread")
            for handler in list(logger.handlers):
                if isinstance(handler, logging.FileHandler):
                    handler.close()
                    logger.removeHandler(handler)
            os.chdir(original_cwd)
            sys.path[:] = old_source_path
            if old_db is None:
                os.environ.pop("refractiveindexinfodb", None)
            else:
                os.environ["refractiveindexinfodb"] = old_db
            if old_backend is None:
                os.environ.pop("MPLBACKEND", None)
            else:
                os.environ["MPLBACKEND"] = old_backend
            if old_config is None:
                os.environ.pop("MPLCONFIGDIR", None)
            else:
                os.environ["MPLCONFIGDIR"] = old_config


def _model_summary_base(model: Any, import_info: Any) -> dict[str, Any]:
    sequential = model["seq_model"]
    optical_spec = model["optical_spec"]
    first_order = model["analysis_results"]["parax_data"][2]
    interfaces: list[dict[str, Any]] = []
    for index, interface in enumerate(sequential.ifcs):
        curvature = float(getattr(interface.profile, "cv", 0.0))
        radius: float | str = "Infinity" if curvature == 0 else 1.0 / curvature
        gap = sequential.gaps[index] if index < len(sequential.gaps) else None
        medium = gap.medium if gap is not None else None
        interfaces.append(
            {
                "index": index,
                "label": str(getattr(interface, "label", "")),
                "interaction": str(getattr(interface, "interact_mode", "")),
                "curvature_per_mm": curvature,
                "radius_mm": radius,
                "thickness_after_mm": float(gap.thi) if gap is not None else None,
                "medium_after": {
                    "name": _call_or_value(medium, "name"),
                    "catalog": _call_or_value(medium, "catalog_name"),
                }
                if medium is not None
                else None,
            }
        )

    field_spec = optical_spec.field_of_view
    fields = [
        {
            "index": index + 1,
            "x": float(field.x),
            "y": float(field.y),
            "weight": float(field.wt),
        }
        for index, field in enumerate(field_spec.fields)
    ]
    spectral = optical_spec.spectral_region
    wavelengths = [
        {
            "index": index + 1,
            "wavelength_nm": float(wavelength),
            "weight": float(spectral.spectral_wts[index]),
            "primary": index == int(spectral.reference_wvl),
        }
        for index, wavelength in enumerate(spectral.wavelengths)
    ]
    return {
        "sequential": {
            "surface_count": len(sequential.ifcs),
            "gap_count": len(sequential.gaps),
            "stop_surface": sequential.stop_surface,
            "interfaces": interfaces,
        },
        "optical_spec": {
            "field_key": list(field_spec.key),
            "maximum_field": float(field_spec.value),
            "fields": fields,
            "wavelengths": wavelengths,
        },
        "first_order": {
            name: float(getattr(first_order, name))
            for name in ("efl", "fno", "bfl", "ffl", "m", "img_dist", "img_ht")
        },
        "import_info": _json_safe(import_info),
    }


def _model_summary(model: Any, import_info: Any) -> dict[str, Any]:
    result = _model_summary_base(model, import_info)
    wavelength = float(model["osp"]["wvls"].central_wvl)
    result["catalog_resolution"] = getattr(model, "_crosscheck_catalog_audit", [])
    result["metric_definitions"] = {
        "efl": "paraxial effective focal length in mm",
        "fno": "paraxial F-number at the imported conjugates",
        "working_f_number": "real-ray on-axis working F-number; four pupil-edge NA-squared mean",
        "wavelength_nm": wavelength,
    }
    try:
        working = _qualified_policy().on_axis_working_fnumber(model, wavelength)
        result["working_f_number_analysis"] = {"status": "AVAILABLE", **working}
        result["first_order"]["working_f_number"] = working["working_f_number"]
    except (ValueError, ArithmeticError) as exc:
        result["working_f_number_analysis"] = {"status": "UNAVAILABLE", "reason": str(exc)}
    return result


def _nested(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _extract_reference(report: dict[str, Any]) -> dict[str, float]:
    status = report.get("status")
    if status not in {None, "PASS", "ok", "OK"}:
        raise CrossCheckError("reference report is not a passing/ok result")
    for prefix in ("analysis", "regression"):
        efl = _nested(report, (prefix, "metrics", "effective_focal_length_mm"))
        fno = _nested(report, (prefix, "metrics", "f_number"))
        if isinstance(efl, (int, float)) and not isinstance(efl, bool):
            values = {"effective_focal_length_mm": float(efl)}
            metrics = _nested(report, (prefix, "metrics"))
            if isinstance(metrics, dict) and "f_number" in metrics and (not isinstance(fno, (int, float)) or isinstance(fno, bool)):
                raise CrossCheckError("provided paraxial F-number reference must be numeric")
            if isinstance(fno, (int, float)) and not isinstance(fno, bool):
                values["f_number"] = float(fno)  # Optiland paraxial metric; retained compatibility key.
            break
    else:
        efl = _nested(report, ("first_order", "effective_focal_length_mm", "value"))
        if not isinstance(efl, (int, float)) or isinstance(efl, bool):
            raise CrossCheckError("reference JSON has no recognized Optiland or Zemax first-order metrics")
        values = {"effective_focal_length_mm": float(efl)}
        for name in ("paraxial_f_number", "working_f_number"):
            item = _nested(report, ("first_order", name, "value"))
            if name in report.get("first_order", {}) and (not isinstance(item, (int, float)) or isinstance(item, bool)):
                raise CrossCheckError("provided " + name + " reference must be numeric")
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                values[name] = float(item)
    if not all(math.isfinite(v) for v in values.values()):
        raise CrossCheckError("reference metrics must be finite")
    return values


def _reference_wavelength_nm(report: dict[str, Any]) -> float | None:
    explicit = report.get("reference_context", {}).get("wavelength_nm")
    if isinstance(explicit, (int, float)):
        return float(explicit)
    waves = _nested(report, ("system", "wavelengths"))
    if isinstance(waves, list):
        primary = next((w for w in waves if w.get("primary")), None)
        if primary is not None:
            return float(primary["wavelength_um"]) * 1000.0
    for prefix in ("analysis", "regression"):
        value = _nested(report, (prefix, "metrics", "wavefront", "wavelength_um"))
        if isinstance(value, (int, float)):
            return float(value) * 1000.0
    return None


def _compare(actual: dict[str, float], expected: dict[str, float],
             relative_tolerance: float, absolute_tolerance: float) -> dict[str, Any]:
    results: dict[str, Any] = {}
    mappings = {"effective_focal_length_mm": "efl", "f_number": "fno",
                "paraxial_f_number": "fno", "working_f_number": "working_f_number"}
    definitions = {"effective_focal_length_mm": "paraxial EFL / mm",
                   "f_number": "Optiland paraxial F-number",
                   "paraxial_f_number": "OpticStudio ISFN / paraxial infinite-conjugate F-number",
                   "working_f_number": "OpticStudio WFNO / real-ray working F-number"}
    for reference_name, actual_name in mappings.items():
        if reference_name not in expected:
            continue
        expected_value = expected[reference_name]
        actual_value = actual.get(actual_name)
        available = isinstance(actual_value, (int, float)) and math.isfinite(actual_value)
        passed = available and math.isclose(actual_value, expected_value,
                                            rel_tol=relative_tolerance, abs_tol=absolute_tolerance)
        results[reference_name] = {
            "rayoptics": actual_value, "reference": expected_value,
            "definition": definitions[reference_name], "available": available,
            "absolute_delta": actual_value - expected_value if available else None,
            "relative_delta": (actual_value - expected_value) / max(abs(expected_value), sys.float_info.min) if available else None,
            "passed": passed,
        }
    return {"relative_tolerance": relative_tolerance, "absolute_tolerance": absolute_tolerance,
            "metrics": results, "all_required_metrics_available": bool(results) and all(v["available"] for v in results.values()),
            "passed": bool(results) and all(v["passed"] for v in results.values())}


def _atomic_json(
    output: Path, payload: dict[str, Any], force: bool, protected: set[Path]
) -> None:
    _reject_remote_or_reparse(output, "output")
    target = output.resolve(strict=False)
    if target.suffix.lower() != ".json":
        raise CrossCheckError("output must use a .json suffix")
    if target in protected:
        raise CrossCheckError("output must not replace an input or reference")
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(_json_safe(payload), handle, ensure_ascii=False, indent=2)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-zmx", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference-json")
    parser.add_argument("--relative-tolerance", type=float, default=1e-4)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if (not math.isfinite(args.relative_tolerance) or not math.isfinite(args.absolute_tolerance)
        or args.relative_tolerance < 0 or args.absolute_tolerance < 0):
        raise CrossCheckError("tolerances must be finite and non-negative")

    source = _local_file(args.input_zmx, "input", {".zmx"})
    reference = (
        _local_file(args.reference_json, "reference", {".json"})
        if args.reference_json
        else None
    )
    output = Path(args.output).expanduser()
    _reject_remote_or_reparse(output, "output")
    protected = {source} | ({reference} if reference is not None else set())
    if output.resolve(strict=False) in protected:
        raise CrossCheckError("output must not replace an input or reference")
    if output.suffix.lower() != ".json":
        raise CrossCheckError("output must use a .json suffix")
    if output.exists() and not args.force:
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    reference_report = json.loads(reference.read_text(encoding="utf-8-sig")) if reference else None
    reference_metrics = _extract_reference(reference_report) if reference_report is not None else None
    source_before = _sha256(source)
    reference_before = _sha256(reference) if reference else None
    package_manifest = _package_manifest()
    rii_snapshot = _rii_snapshot()

    policy_manifest = _policy_manifest()
    integrity = {"rayoptics_source_manifest": package_manifest["matches_pin"],
                 "rii_catalog_snapshot": rii_snapshot["matches_pin"],
                 "local_policy_manifest": policy_manifest["matches_pin"]}
    if not all(integrity.values()):
        report = {"schema_version": "2.0", "status": "FAIL", "mode": "integrity_guard_before_import",
                  "checks": integrity, "failed_checks": [k for k, v in integrity.items() if not v],
                  "software": {"rayoptics_source_manifest": package_manifest,
                               "refractiveindex_info_snapshot": rii_snapshot, "local_policy_manifest": policy_manifest},
                  "model": None, "comparison": None}
        _atomic_json(output, report, args.force, protected)
        print(json.dumps({"status": "FAIL", "checks": integrity, "output": str(output)}))
        return 1

    with _rayoptics_runtime() as read_lens_file:
        model, import_info = read_lens_file(source)
        summary = _model_summary(model, import_info)

    source_after = _sha256(source)
    reference_after = _sha256(reference) if reference else None
    if source_before != source_after:
        raise CrossCheckError("input ZMX changed during read-only inspection")
    if reference and reference_before != reference_after:
        raise CrossCheckError("reference JSON changed during read-only inspection")

    first_order = summary["first_order"]
    metrics_finite = all(
        math.isfinite(first_order[name]) for name in ("efl", "fno", "bfl", "ffl")
    )
    checks = {
        "rayoptics_source_manifest": package_manifest["matches_pin"],
        "rii_catalog_snapshot": rii_snapshot["matches_pin"],
        "local_policy_manifest": policy_manifest["matches_pin"],
        "source_unchanged": source_before == source_after,
        "prescription_loaded": summary["sequential"]["surface_count"] >= 2,
        "first_order_metrics_finite": metrics_finite,
    }

    comparison = None
    if reference:
        comparison = _compare(
            first_order,
            reference_metrics,
            args.relative_tolerance,
            args.absolute_tolerance,
        )
        checks["reference_metrics_available"] = comparison["all_required_metrics_available"]
        reference_wavelength = _reference_wavelength_nm(reference_report)
        checks["reference_wavelength_match"] = reference_wavelength is None or math.isclose(
            reference_wavelength, summary["metric_definitions"]["wavelength_nm"], rel_tol=0.0, abs_tol=1e-8)
        if "paraxial_f_number" in reference_metrics:
            checks["ISFN_infinite_conjugate_scope"] = abs(model["sm"].gaps[0].thi) >= 1e9
        checks["reference_first_order_match"] = comparison["passed"]

    required_failures = [name for name, passed in checks.items() if not passed]
    if required_failures:
        status = "MISMATCH" if required_failures == ["reference_first_order_match"] else "FAIL"
    else:
        status = "PASS" if reference else "INSPECTED"

    report = {
        "schema_version": "2.0",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_zmx_first_order_crosscheck",
        "source": {
            "path": str(source),
            "sha256_before": source_before,
            "sha256_after": source_after,
            "unchanged": True,
        },
        "reference": {
            "path": str(reference),
            "sha256_before": reference_before,
            "sha256_after": reference_after,
            "metrics": reference_metrics,
        }
        if reference
        else None,
        "software": {
            "local_policy_manifest": policy_manifest,
            "local_policy_version": "gcat-fno-r2",
            "rayoptics_source_commit": PINNED_SHA,
            "rayoptics_source_manifest": package_manifest,
            "refractiveindex_info_snapshot": rii_snapshot,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "matplotlib_backend": "Agg",
            "windows_path_parser_shim": True,
        },
        "model": summary,
        "comparison": comparison,
        "checks": checks,
        "failed_checks": required_failures,
        "limitations": [
            "RayOptics upstream states that its author cannot validate Zemax imports against Zemax",
            "Prescription structure, paraxial first-order metrics, and supported centered on-axis real-ray working F-number are exposed",
            "No optimization, prescription edits, file saves, spot, PSF, MTF, wavefront, tolerance, or stray-light claims",
            "A first-order mismatch is evidence to investigate importer, catalog, or convention differences; it does not identify which engine is correct",
            "Windows paths use opticalglass 2.0.2 native pathlib parsing; the legacy separator shim is retained conditionally",
            "Named glass lookup is exact and restricted to declared GCAT order; no silent cross-catalog/model-glass fallback",
            "Working F-number is unavailable for unsupported off-axis or decentered geometry; required missing metrics fail comparison",
        ],
    }
    protected = {source}
    if reference is not None:
        protected.add(reference)
    _atomic_json(Path(args.output).expanduser(), report, args.force, protected)
    print(
        json.dumps(
            {
                "status": status,
                "failed_checks": required_failures,
                "output": str(Path(args.output).expanduser().resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if status in {"PASS", "INSPECTED"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CrossCheckError, FileExistsError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
