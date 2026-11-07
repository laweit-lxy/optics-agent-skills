---
name: design-optical-systems
description: Analyze a local sequential lens prescription (absolute-path .zmx) or the built-in Cooke/Double-Gauss/Hubble samples with the pinned Optiland 0.6.3 runtime, reporting EFL/F-number, spot, OPD, scalar FFT PSF/MTF and a three-point radius sensitivity, read-only. Use when an agent needs reproducible geometric/wavefront metrics or Optiland runtime qualification. Not for wave-optics propagation or inverse design (analyze-optical-designs), independent cross-software checks (cross-check-optical-designs), or editing/optimizing in OpticStudio (ai-zemax-optical-design).
---

# Design Optical Systems

## Purpose

Generate reproducible optical-design metrics while keeping prescription source files read-only and separating numerical self-consistency from cross-software validation.

## Workflow

1. Read `references/runtime-lock.md` and use only the pinned environment.
2. Preserve the source prescription, reject URLs and symlinks, and record its SHA-256 digest.
3. Run `--self-test` only when you need environment qualification by itself. To analyze a ZMX, run `--input-zmx` directly: it includes the same qualification and skips user-data analysis if qualification fails, so do not also run a separate self-test. Keep the built-in acceptance gate intact.
4. For a local absolute-path `.zmx`, run the script with `--input-zmx` and write to a new JSON output. UNC paths and any symlink/junction path component are rejected; the report can never replace the source, including with `--force`.
5. Review every `checks` entry and the `limitations` section. Treat a failed or skipped metric as unresolved rather than filling it with an estimate.


## Adjacent Skills

- This skill: geometric ray tracing of sequential prescriptions and the scalar FFT PSF/MTF derived from those traces.
- `analyze-optical-designs`: wave-optics propagation defined on pupils or fields, and inverse design.
- `cross-check-optical-designs`: the independent second opinion. This skill does not compare itself with other software; Optiland vs. OpticStudio discrepancies are judged there.

## Commands

Install the pinned environment once from this skill's `requirements.txt` (see `references/runtime-lock.md`). `<python>` is that environment's interpreter and `<skill-dir>` is this skill's folder.

```bash
<python> <skill-dir>/scripts/optiland_regression.py --self-test --output /absolute/new-result.json
<python> <skill-dir>/scripts/optiland_regression.py --input-zmx /absolute/source.zmx --output /absolute/new-result.json
```

The self-test uses Optiland's synthetic/reference Cooke triplet, Double-Gauss, and Hubble telescope. It also checks immutable Hubble constants measured independently in OpticStudio 2023 R1.02. It is software verification, not a measured optical-system acceptance test.

## Required Interpretation

- Prescription distances and radii are millimetres; wavelengths are micrometres; spatial frequency is cycles/mm; OPD RMS is waves at the stated wavelength.
- Spot metrics are geometric ray metrics. FFT PSF/MTF are scalar calculations in the pinned NumPy backend; every report records requested and actual pupil sampling, FFT grid, strategy, and tilt handling.
- Sensitivity uses a deterministic three-point radius sweep and verifies that the nominal prescription is restored. It is not a manufacturing Monte Carlo or a tolerance yield claim.
- JSON equality and ZMX import/export are self-round-trips. They do not demonstrate semantic equivalence in Ansys Zemax OpticStudio.
- The pinned writer preserves binary64 numeric precision and emits Nd/Vd so the reader can disambiguate duplicate glass names inside declared `GCAT` catalogs. The regression requires Cooke catalog identity, actual n(λ) at all system wavelengths, and EFL to survive the self-round-trip. This does not guarantee every third-party importer will select the same catalog.
- Independent Hubble values must never be regenerated from Optiland. If they fail, investigate the implementation, definition/convention, or external reference before changing a constant or tolerance.
- Hubble RMS wavefront reduction is still sampling-limited, and the tangential field-curvature comparison remains a strict upstream `xfail`. Both are accepted long-term as non-blocking findings: keep them visible, do not loosen their thresholds or drop them to obtain a green report, and re-evaluate them at the next Optiland upgrade.
- `--input-zmx` results cover only the surfaces and keywords Optiland parses; unsupported features may be silently ignored. Compare the reported `surface_count`, radii, thicknesses and stop with the source file before relying on the metrics.
- External compatibility remains version-specific. The repository's sample references came from OpticStudio 22.2.2 and were reproduced in OpticStudio 2024 R1, while the immutable upstream Hubble constants came from OpticStudio 2023 R1.02.
- Stray light, ghost analysis, non-sequential propagation, optomechanical coupling, coating manufacturing data, and full commercial-file feature coverage are outside this regression.

## Acceptance Gate

Accept the runtime baseline only when:

- the source commit, installed-code manifest hash/count, and Python platform are recorded and the installed manifest matches the frozen value;
- Cooke prescription, EFL, F/#, spot arrays, OPD RMS, PSF, and MTF checks pass;
- the tolerance sweep is finite and restores the nominal radius;
- Optiland JSON round-trip is identical;
- Hubble and Double-Gauss ZMX self-round-trips preserve paraxial quantities at `rtol=1e-12` and real-ray image intercepts at `atol=1e-9`;
- Cooke surface-group EFL/ABCD composition passes without treating isolated group powers as additive system power;
- Cooke glass identity, actual n(λ), and EFL survive ZMX round-trip, and the float formatter recovers hard binary64 values exactly;
- Hubble first-order quantities, six real-ray intercepts, and two-field spot radii agree with immutable OpticStudio 2023 R1.02 references at their stated tolerances;
- the unresolved Hubble wavefront-sampling and tangential-field-curvature findings remain present and non-blocking; if either unexpectedly passes, treat it as a behavior change and investigate before updating documentation;
- the report retains all compatibility limitations.
