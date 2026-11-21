# RayOptics runtime lock (policy r2)

## Pinned runtime

- Upstream: https://github.com/mjhoptics/ray-optics (BSD-3-Clause), commit `5009d933ae525defcd799344ad94f80cc6177892`, package `0.9.10.post1.dev10+g5009d933a`. It includes the upstream fixes for inch units (`UNIT IN`/`INCH`) and for the infinite-object stand-in distance (see Policy behavior). The previous pin was `e25bc579116d31ed97fa1632f871e2801e8e956e`.
- Installed through pip from that commit (`requirements.txt`). The entry reads the commit pip records in `direct_url.json` and also recomputes a package manifest of the upstream Git tree (192 files, SHA-256 `73a22ea794d88134582424b78f1112c7989ab973e90ec8c34affb415204d1111`). Either matching the pin qualifies the source; a manifest difference alone usually means line-ending conversion at checkout and is recorded in the report. A fresh pip install from GitHub on Windows (2026-11-16 UTC) recorded the pinned commit; with Git's `core.autocrlf=true`, 148 of its 192 files were checked out with CRLF line endings and no other byte differed, so its manifest is `230a1fe3ae43ab6f4b540d4fd559e901b209240d538c2c793c67774eb28bea85` and the commit qualifies it.
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
- RayOptics keeps lengths in the file's unit (`model.system_units`). The report converts curvature to 1/mm and radii, thicknesses, first-order lengths (`efl`, `bfl`, `ffl`, `img_dist`, `img_ht`) and height fields to mm. F-numbers, magnification, indices and angle fields are unchanged. `model.import_info` keeps the original system units. The diagnosis probe uses the same units for its reported lengths.
- RayOptics replaces an infinite object with a finite distance chosen for about 1 nm of image shift (f²/z, clamped to 1e10–1e20 in the file's unit) and records it in `import_info` as `inf object`: 1e10 mm for Cooke, 10000749588.2 mm for Double-Gauss, about 3.3e15 mm for Hubble. An explicitly finite object distance is kept unchanged.
- A process-local Windows path shim, temporary cwd and Matplotlib cache, environment restoration, strict local paths, atomic output writing, source/reference hashes and explicit `--force` are retained. No installed package is patched; the catalog handler replacement is restored in `finally`.

## Regression evidence

The three samples in `tests/data/` pass the unchanged relative 1e-4 and absolute 1e-8 thresholds for EFL, paraxial F-number and real working F-number against independently measured OpticStudio 22.2.2 references (reproduced in OpticStudio 2024 R1 within `rtol=atol=1e-10`):

- Cooke: EFL 50.00039433779174 mm; real working F-number 4.978262613802968.
- Double-Gauss: EFL 100.0037478708372 mm; real working F-number 4.992598837826468.
- Hubble: EFL 57600.080998403595 mm; paraxial and real working F-number residuals about 1.4e-10 relative. This is not a claim of bitwise equality.
- The same Hubble prescription rewritten in `UNIT IN` and `UNIT INCH` reports the same mm values and passes the same comparison (`tests/test_cross_check_optical_designs.py`).

## Scope and requalification

Qualified for the three centered samples, not for arbitrary custom/ZAR catalogs, all conjugates, off-axis/decentered WFNO, GUI, spot/PSF/MTF, optimization or stray light. Do not turn an unavailable quantity into PASS or loosen tolerances. Any source, policy, dependency, database, parser, reference schema or numerical-definition change requires rerunning the repository test suite.
