---
name: analyze-optical-designs
description: Scalar wave-optics analysis with the pinned Chromatix/Prysm runtime, covering Fresnel/Fraunhofer/angular-spectrum propagation, pupil- or Zernike-based PSF/MTF/OTF, computational imaging, and differentiable inverse design. Not for sequential lens prescriptions (use design-optical-systems), ZMX cross-checks (cross-check-optical-designs), or OpticStudio (ai-zemax-optical-design).
---

# Analyze Optical Designs

Use a dedicated Python 3.12 environment installed from this skill's `requirements.txt` (see `references/runtime-lock.md`). Below, `<python>` is that environment's interpreter and `<skill-dir>` is this skill's folder.

## Workflow

1. Read the optical prescription, pupil, sampling, wavelength, refractive index, focal length, detector pitch, units, and expected outputs.
2. Preserve all source files. Write generated arrays, figures, and reports to a new output directory.
3. Choose the numerical engine:
   - Use Chromatix for JAX-based differentiable wave optics, computational imaging, PSF engineering, and inverse design.
   - Use Prysm for physical-optics propagation, pupil and aberration models, PSF/MTF/OTF, detectors, interferometry, and engineering metrics.
   - Use both for cross-checks when their physical assumptions overlap.
4. Record sampling, normalization, propagation convention, boundary treatment, backend, package versions, and pinned Git commits.
5. Qualify the runtime with `scripts/optics_regression.py --self-test` before its first numerical use, after dependency or regression-code changes, or when numerical failures cast doubt on it. Reuse a passing result only while `requirements.txt` and `scripts/optics_regression.py` are unchanged; task-specific physical checks still apply.
6. Validate conservation or normalization where physically applicable and report numerical tolerances.
7. Mark comparisons to Zemax, CODE V, measured hardware, or published data as unverified unless the corresponding source is supplied.

## Safety And Reproducibility

- Do not control cameras, SLMs, stages, lasers, or other instruments from this skill.
- Do not overwrite prescriptions, measured data, calibration files, or prior results.
- Never invent material constants, coating data, tolerances, or detector parameters.
- Use SI units internally unless a library API explicitly requires another unit; label every conversion.
- Fix random seeds for stochastic optimization and save the seed with results.
- Use the JAX CPU backend. GPU is not qualified; enable it only after checking JAX and driver compatibility, and record the backend.
- Pin new dependencies or upstream revisions before adding them to the workflow.

## Regression Command

```bash
<python> -I <skill-dir>/scripts/optics_regression.py --self-test
```

The command must exit 0 with `passed: true`, which requires matching commit pins, an installed set identical to `requirements.txt` (pytest and its helpers are reported but ignored), and passing `chromatix`, `prysm`, `chromatix_gradient`, and `prysm_analytic_mtf` checks. Read `references/runtime-lock.md` when recreating, auditing, or updating the runtime.

## Reporting

Report inputs, units, assumptions, backend, package/commit provenance, commands, numerical checks, output paths, and unresolved physical uncertainties. Separate simulated results from measured or externally validated results.
