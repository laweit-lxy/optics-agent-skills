#!/usr/bin/env python3
"""Diagnose why Optiland and RayOptics disagree on a local .zmx prescription.

Standard library only; run with any Python 3.10+. The probes run in the
design-optical-systems and cross-check-optical-designs environments, located by
OPTICS_SKILLS_PYTHON_DESIGN / OPTICS_SKILLS_PYTHON_CROSSCHECK or <repo>/.venv-<skill>.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from optics_agent_skills.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["diagnose", *sys.argv[1:]]))
