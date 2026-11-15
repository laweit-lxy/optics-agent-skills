---
name: calibrate-spectral-wavelength
description: Calibrate supplied one-dimensional peak pixels to air or vacuum wavelengths with pinned RASCAL 0.3.11, using a lamp atlas or custom lines and optional independent holdouts. Reports polynomial units, assignments, rejected peaks and residuals. Use for pixel-to-wavelength calibration or RASCAL qualification; not peak finding, 2D extraction, plotting, sequential lens analysis (design-optical-systems), or wave propagation (analyze-optical-designs).
---

# Calibrate Spectral Wavelength

## Workflow

1. Read `references/input-schema.md` and prepare one local JSON input with explicit medium, detector length, increasing wavelength range and a maximum nonlinear deviation from the endpoint chord. Use the caller's line table and accuracy requirements; the bundled sparse example is synthetic.
2. Use the pinned interpreter in `references/runtime-lock.md`. Read inputs only; select an absolute output directory that does not exist and whose parent exists. URLs, UNC paths and symlink/reparse path components are rejected.
3. Run `scripts/calibrate.py`. Every call checks the pinned distributions and imports before fitting, explicitly sets both `num_pix` and the full `pixel_list`, isolates holdout peaks/atlas lines, and hashes the input before and after execution. A separate environment self-check is needed only for environment qualification alone.
4. Read `report.json`: require `status=PASS`, all `checks=true`, and unchanged input. Use `polynomial.coefficients` only in a PASS report. A failed fit or acceptance gate produces exit 1 and `polynomial=null`; preserve its error and any diagnostics. A path refusal produces exit 2 without overwriting the target.
5. Report fit RMS, holdout RMS/max error or absent holdout, peak utilisation, assignments/rejections, medium, units, seed and input SHA-256. Distinguish a reproducible fit from independently validated accuracy.

## Run

Install the pinned environment once from this skill's `requirements.txt` (see `references/runtime-lock.md`). `<python>` is that environment's interpreter and `<skill-dir>` is this skill's folder. Paths are absolute; the output directory must not exist yet, and an existing one, even empty, is refused.

```bash
<python> -X utf8 -I <skill-dir>/scripts/calibrate.py --input <skill-dir>/examples/input.json --output-dir /absolute/new-output-dir
```

The bundled `examples/input.json` is a synthetic Hg/Ar/Ne case with 27 peaks and 6 holdout lines. For user data, replace the input argument. `scripts/contract.py --output-dir <absolute/new-directory>` checks the environment without a fit. Run it with the same pinned Python and `-X utf8 -I`.

## Interpretation and limits

- Power basis, ascending coefficients: `lambda_nm = sum(c[k] * pixel**k)`, zero-based detector coordinates. Coefficient k has unit `nm/pixel^k`; the constant has unit `nm`. Output is in the declared air/vacuum medium.
- RASCAL internally uses Angstrom. Built-in NIST loading converts vacuum to air once when requested. Custom wavelengths already have the declared medium; `Atlas.add_user_atlas(vacuum=False)` inserts them unchanged even for vacuum output. Air conditions are explicit in the report.
- The candidate corridor is derived from the supplied maximum chord deviation; its width is separate from the fixed 0.10 nm fit/inlier tolerance. Correct the physical bound or input when evidence warrants it; keep acceptance thresholds intact. The library's destructive close-line filter is disabled. Optional strongest-per-bin greedy selection keeps one eligible line and records the selection.
- Sigma inputs are retained and converted with the local polynomial derivative. RANSAC uses no measurement-sigma weights; these values are not coefficient confidence intervals. A rejected peak has no accepted atlas assignment; its physical cause is unresolved.
- Supported input degrees are 1–5 and increasing dispersion only. Qualification covers a quadratic Hg/Ar/Ne synthetic case, not every degree or real lamp spectrum. Supplied holdout pixels and line identities are excluded before fitting; caller-selected holdouts must be independent measurements for independent instrument validation.
- Acceptance requires at least `max(10, degree+3)` matches, utilisation >=0.6, fit RMS <=0.10 nm, positive dispersion throughout the detector and fitted endpoints within 10 nm of the requested range. When holdouts exist, RMS <=0.10 nm and max absolute error <=0.20 nm are required. Failed gates withhold coefficients. Without holdouts, PASS covers internal fit checks only.
- RASCAL 0.3.11 has a known unique-candidate aggregation issue. Installed code is unchanged; duplicate/ambiguous returned assignments are rejected. Dense or blended line reliability remains unqualified.
- Automatic peak finding, 2D spectrum extraction and plotting are outside scope. Lens prescription analysis belongs to `design-optical-systems`; wave optics to `analyze-optical-designs`. This skill leaves optical prescriptions and `spectrometer/` untouched.

## Regression

Run `tests/regression.py --output-dir <absolute/new-directory>` using the pinned Python and `-X utf8 -I`. It invokes the real CLI in fresh processes, reproduces seed 20261115, checks three additional seeds, lamp/custom medium branches, holdout isolation and explicit failure paths. Read its `regression.json` and per-case reports. Its thresholds are fixed in the file. The repository runs it on Linux and Windows through `tests/test_calibrate_spectral_wavelength.py`.
