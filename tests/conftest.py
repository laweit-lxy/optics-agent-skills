from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "tests" / "data"
SAMPLES = ("cooke", "double-gauss", "hubble")


def sample_zmx(name: str) -> Path:
    return DATA / name / f"{name}-6cd4da4.zmx"


def sample_reference(name: str) -> Path:
    return DATA / name / f"{name}-native-reference.json"


def unit_copy(source: Path, target: Path, unit: str, object_distance_mm: float | None = None,
              height_field: bool = False) -> Path:
    """Write a millimetre .zmx in another declared unit (MM, IN or INCH), rescaling its lengths.

    Covers the records in the bundled samples: ENPD, CURV, DISZ and CLAP, plus XFLN/YFLN
    when ``height_field`` turns the fields into object heights. ``object_distance_mm``
    replaces the infinite object distance with a finite one.
    """
    mm = {"MM": 1.0, "IN": 25.4, "INCH": 25.4}[unit]
    lines = []
    for line in source.read_text(encoding="utf-8").splitlines():
        indent = line[: len(line) - len(line.lstrip())]
        key, *values = line.split() or [""]
        if key == "UNIT":
            values[0] = unit
        elif key == "FTYP" and height_field:
            values[0] = "1"
        elif key == "DISZ" and values[0] == "INFINITY":
            if object_distance_mm is not None:
                values[0] = repr(object_distance_mm / mm)
        elif key == "CURV":
            values[0] = repr(float(values[0]) * mm)
        elif key in {"ENPD", "DISZ", "CLAP"}:
            values[0] = repr(float(values[0]) / mm)
        elif key in {"XFLN", "YFLN"} and height_field:
            values = [repr(float(v) / mm) for v in values]
        lines.append(indent + " ".join([key, *values]) if key else line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_entry(script: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a skill entry with the interpreter running the tests, as an agent would."""
    return subprocess.run(
        [sys.executable, "-I", str(script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
    )


def read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path.resolve()
