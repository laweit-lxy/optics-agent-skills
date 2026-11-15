# CadQuery runtime lock

## Pinned runtime

- Repository: https://github.com/CadQuery/cadquery (Apache-2.0).
- Release `2.8.0` from PyPI with cadquery-ocp 7.9.3.1.1 (OCCT bindings). Python 3.12, 64-bit. VTK 9.6.2, NumPy 2.5.4, SciPy 1.18.1; the full set of 44 distributions is in `requirements.txt`.
- The lock pins versions, not wheel hashes. Library source is used unmodified.
- CPU only, no GUI: CQ-editor, viewers and the trame server are never started. Matplotlib configuration is process-local inside the new output directory.

Install into a dedicated virtual environment (about 1.2 GB):

```bash
python3.12 -m venv .venv-build-optomechanical-parts
.venv-build-optomechanical-parts/bin/python -m pip install -r requirements.txt   # Windows: .venv-build-optomechanical-parts\Scripts\python.exe
```

## Runtime gate

`references/runtime.json` lists the modules that must import. `scripts/contract.py` requires isolated UTF-8 mode (`-X utf8 -I`), 64-bit Python 3.12 and every distribution in `requirements.txt` at its pinned version, then imports the engine without visualization. Every build runs this gate first. Distributions outside the lock (pip, a test runner) are listed in the report as `unpinned_distributions` and do not fail the gate.

## Library behavior the script works around

CadQuery's default `BoundingBox` uses an existing triangulation when the shape has one. After an STL export of a rotated solid, the cached mesh changed the reported bounds by 0.0062 mm. The script measures bounds with OCCT `BRepBndLib.AddOptimal_s(shape, box, False, False)`, which ignores the triangulation and adds no tolerance gap, so the 1e-6 mm STEP bound gate applies to the exact B-rep.

## Qualification

`tests/regression.py` runs the command line in fresh processes and checks, against values it computes itself: analytic volume of the mount and the baffled tube (relative error at most 1e-9), bounds (1e-6 mm), parameter rebuilds, STEP roundtrip (relative volume 1e-8, bounds 1e-6 mm), binary STL length, matrix and axis-angle assembly poses (1e-12), the centroid of a transformed solid (1e-9 mm), rejection of an oversized aperture and of a reflection matrix, and refusal to reuse an output directory. First qualified on Windows 11 (x64 Python 3.12.14): 22 checks passed.

Hierarchy and poses read back from the named assembly STEP, import into other CAD programs, tolerances, threads and clearances are not qualified.

## Changing the pin

A change to the CadQuery or OCP version, or any dependency, requires rerunning `tests/regression.py` and updating this file.
