# RayOptics runtime lock (policy r2)

## Pinned runtime

- Upstream: https://github.com/mjhoptics/ray-optics (BSD-3-Clause), commit `e25bc579116d31ed97fa1632f871e2801e8e956e`, package `0.9.10.post1.dev6+ge25bc5791`.
- Installed through pip from that commit (`requirements.txt`). The entry reads the commit pip records in `direct_url.json` and also recomputes a package manifest (192 files, SHA-256 `76b2b57d9b5db8b91fd34f1e5ef971cc7c57752e1b1e3d858ce0302d3c106924`). Either matching the pin qualifies the source; a manifest difference alone usually means line-ending conversion at checkout and is recorded in the report. A fresh pip install from GitHub on Windows (2026-11-06) matched both.
- Python 3.12; opticalglass 2.0.2, NumPy 2.5.1, SciPy 1.18.0; the full set is in `requirements.txt`.
- The catalog/F-number policy `scripts/rayoptics_local_policy.py` is versioned with the entry; the report records its SHA-256.

Install into a dedicated virtual environment (Git is required for the pinned source):

```bash
python3.12 -m venv .venv-cross-check-optical-designs
.venv-cross-check-optical-designs/bin/python -m pip install -r requirements.txt   # Windows: .venv-cross-check-optical-designs\Scripts\python.exe
```

## Optional material database

GCAT lookups use the vendor catalogs bundled with opticalglass. A refractiveindex.info database snapshot is optional: set `OPTICS_SKILLS_RII_DB` to its root. When set, the entry checks the snapshot below and fails if it differs; when unset, the report records `configured: false`.

- 4,174 files; `catalog-nk.yml` SHA-256 `3a4a18908b03b99e258f4f329d8fc56e7d79757902a5153a212508a19a146cf1`; `catalog-n2.yml` SHA-256 `42db48e7361281e863c9d1995081cf87ba945477ecdc6ab4aae090e4cee1ae92`.

## First-run SyntaxWarning

The first import after installing compiles upstream modules and prints about ten `SyntaxWarning: invalid escape sequence` lines from docstrings. Later runs are silent. This is expected; do not patch upstream files.

## Policy behavior

- Named glass lookup obeys the declared GCAT order with exact names and no unrelated-catalog or model-glass fallback. Cooke resolves F2 to Hikari; Double-Gauss resolves F5 to Schott. Explicit blank, mirror and numeric records keep the original parser path.
- Paraxial F-number is compared with native ISFN, and real-ray working F-number with native WFNO. The latter traces the chief ray and four vignetted pupil-edge rays for centered on-axis systems; unsupported geometry fails a required working-F-number comparison.
- A process-local Windows path shim, temporary cwd and Matplotlib cache, environment restoration, strict local paths, atomic output writing, source/reference hashes and explicit `--force` are retained. No installed package is patched; the catalog handler replacement is restored in `finally`.

## Regression evidence

The three samples in `tests/data/` pass the unchanged relative 1e-4 and absolute 1e-8 thresholds for EFL, paraxial F-number and real working F-number against independently measured OpticStudio 22.2.2 references (reproduced in OpticStudio 2024 R1 within `rtol=atol=1e-10`):

- Cooke: EFL 50.00039433779174 mm; real working F-number 4.978262613802968.
- Double-Gauss: EFL 100.0037478708372 mm; real working F-number 4.992598837826468.
- Hubble: EFL 57600.080998403595 mm; its F-number residual is near 4.8e-5 relative, within 1e-4. This is not a claim of bitwise equality.

## Scope and requalification

Qualified for the three centered samples, not for arbitrary custom/ZAR catalogs, all conjugates, off-axis/decentered WFNO, GUI, spot/PSF/MTF, optimization or stray light. Do not turn an unavailable quantity into PASS or loosen tolerances. Any source, policy, dependency, database, parser, reference schema or numerical-definition change requires rerunning the repository test suite.
