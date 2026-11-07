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
