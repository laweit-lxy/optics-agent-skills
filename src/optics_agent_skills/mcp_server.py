"""MCP server exposing the pinned optics engines and the discrepancy diagnosis.

Every tool is read-only toward the input prescription and writes its reports
under a new directory inside ``OPTICS_SKILLS_OUTPUT_ROOT`` (default
``./optics-agent-output``). Engines run in their own pinned environments; see
``optics_agent_skills.engines``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__, engines

mcp = MCPServer("optics-agent-skills", version=__version__)


def _call(function, *args):
    """Run an engine call; report input, safety and engine failures as tool errors."""
    try:
        return function(*args)
    except (engines.EngineError, FileExistsError, ValueError, OSError) as exc:
        raise ToolError(str(exc)) from exc


def _run_dir(label: str) -> Path:
    root = Path(os.environ.get("OPTICS_SKILLS_OUTPUT_ROOT", "optics-agent-output")).expanduser().resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"{label}-{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _summary(report: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: report.get(key) for key in keys}


@mcp.tool()
def list_samples() -> list[dict[str, str]]:
    """List the bundled regression prescriptions and their OpticStudio references."""
    data = engines.REPO / "tests" / "data"
    if not data.is_dir():
        raise ToolError(f"bundled samples not found at {data}; install from a repository checkout (pip install -e)")
    return [{"name": folder.name,
             "zmx": str(next(folder.glob("*.zmx"))),
             "opticstudio_reference": str(next(folder.glob("*-native-reference.json")))}
            for folder in sorted(p for p in data.iterdir() if p.is_dir())]


@mcp.tool()
def analyze_prescription(zmx_path: str) -> dict[str, Any]:
    """Analyze an absolute-path .zmx with pinned Optiland: EFL, F-number, spot, OPD, PSF/MTF.

    Runs the design-optical-systems qualification first; a failed qualification
    skips the analysis. Returns status, failed checks, metrics and the report path.
    """
    output = _run_dir("analyze") / "optiland-report.json"
    report = _call(engines.analyze_prescription, zmx_path, output)
    analysis = report.get("analysis", {})
    return {"status": report["status"], "failed_checks": report.get("failed_checks", []),
            "metrics": analysis.get("metrics"), "limitations": report.get("limitations"),
            "report_path": str(output)}


@mcp.tool()
def cross_check_prescription(zmx_path: str, reference_json_path: str | None = None) -> dict[str, Any]:
    """Independently load an absolute-path .zmx with pinned RayOptics and compare first-order metrics.

    With a reference (an Optiland report or an OpticStudio export) the status is
    PASS or MISMATCH; without one it is INSPECTED. FAIL means an integrity gate failed.
    """
    output = _run_dir("cross-check") / "rayoptics-report.json"
    report = _call(engines.cross_check, zmx_path, output, reference_json_path)
    return {**_summary(report, ("status", "failed_checks", "comparison")),
            "first_order": report.get("model", {}).get("first_order") if report.get("model") else None,
            "catalog_resolution": report.get("model", {}).get("catalog_resolution") if report.get("model") else None,
            "report_path": str(output)}


@mcp.tool()
def diagnose_discrepancies(zmx_path: str, reference_json_path: str | None = None) -> dict[str, Any]:
    """Explain why Optiland and RayOptics disagree on an absolute-path .zmx.

    Compares the prescription each engine built (geometry, stop, wavelengths, glass
    catalog and index per surface), first-order quantities and real rays, then runs
    elimination experiments (glass-catalog swap, real ray aiming). Status is AGREE,
    EXPLAINED or UNRESOLVED, with confirmed causes and open items.
    """
    output_dir = _run_dir("diagnose")
    report = _call(engines.diagnose, zmx_path, output_dir, reference_json_path)
    return {**_summary(report, ("status", "causes", "unresolved",
                                  "input_differences_without_confirmed_effect", "reference", "limitations")),
            "experiments": [{k: e.get(k) for k in ("name", "status", "kept", "removed", "settings", "efl_mm_after",
                                                    "reason")}
                            for e in report["experiments"]],
            "report_path": str(output_dir / "diagnosis.json")}


@mcp.tool()
def wave_optics_self_test() -> dict[str, Any]:
    """Qualify the pinned Chromatix/Prysm wave-optics environment and return each check."""
    output = _run_dir("wave-self-test") / "self-test.json"
    report = _call(engines.wave_self_test, output)
    return {**report, "report_path": str(output)}


@mcp.tool()
def server_info() -> dict[str, Any]:
    """Report the package version and which engine environments are available."""
    available = {}
    for engine, (skill, variable) in engines.ENGINES.items():
        try:
            available[skill] = str(engines.interpreter(engine))
        except engines.EngineError as exc:
            available[skill] = f"unavailable: {exc}"
    return {"version": __version__, "skills_root": str(engines.SKILLS), "engines": available}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
