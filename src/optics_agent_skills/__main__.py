"""Command line: python -m optics_agent_skills <command> ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import engines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="optics_agent_skills", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    diagnose = commands.add_parser("diagnose", help="explain differences between Optiland and RayOptics")
    diagnose.add_argument("--input-zmx", required=True)
    diagnose.add_argument("--output-dir", required=True, type=Path)
    diagnose.add_argument("--reference-json", help="OpticStudio reference with first_order EFL")
    diagnose.add_argument("--force", action="store_true")

    commands.add_parser("serve", help="run the MCP server over stdio")

    args = parser.parse_args(argv)
    if args.command == "serve":
        from .mcp_server import main as serve
        serve()
        return 0
    try:
        report = engines.diagnose(args.input_zmx, args.output_dir, args.reference_json, args.force)
    except (engines.EngineError, FileExistsError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    summary = {"status": report["status"],
               "causes": [c["category"] for c in report["causes"]],
               "unresolved": [u["category"] for u in report["unresolved"]],
               "without_confirmed_effect": [d["category"] for d in
                                            report["input_differences_without_confirmed_effect"]],
               "output": str(args.output_dir.resolve() / "diagnosis.json")}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report["status"] in ("AGREE", "EXPLAINED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
