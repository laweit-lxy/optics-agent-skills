# Roadmap

A release every two weeks. Each release must keep the regression suite green on Linux and Windows.

| Version | Target | Scope |
| --- | --- | --- |
| v0.1.0 | 2026-11-06 (released) | `design-optical-systems` (Optiland) and `cross-check-optical-designs` (RayOptics); portable pinned environments; Cooke, Double-Gauss and Hubble regressions against OpticStudio references; CI; Claude Code plugin and Codex install. |
| v0.2.0 | 2026-11-20 | `analyze-optical-designs` (Chromatix/Prysm wave optics). `diagnose-optical-discrepancies`: compare the prescription each engine built, first-order values and real rays, and run elimination experiments (glass catalog, object distance, ray aiming). Shared standard-library core package with a command line and an MCP server over it. |
| v0.2.1 | 2026-11 | Audit fixes: the diagnosis never writes through an alias of its input and rechecks the input hash after writing; it validates both probe reports, treats missing or newly untraceable rays and non-finite first-order values as unresolved, reports different fields or wavelengths as not comparable; the Optiland probe enforces the pinned code manifest; editable-install requirement stated. |
| v0.3 | 2026-12-04 | `process-radiometric-calibration` (SRF convolution, TOA reflectance, MC/GUM uncertainty). Starting-point library of classic lens forms from expired patents and public literature, each with its source. Diagnosis: experiments for the remaining pupil-edge ray differences (pupil coordinate definition, vignetting), surface-by-surface import comparison. |
| v0.4 | 2026-12-18 | Requirements-to-lens design loop: pick a starting form, optimize with Optiland (including the differentiable Torch backend), run Monte Carlo tolerancing and yield, then verify independently with the cross-check engines. Scope: rotationally symmetric spherical and aspheric systems, visible and near infrared. |
| v0.5 | 2027-01-01 | `optics-bench`: 20–30 lens design tasks scored on requirement attainment, cost (element count, length) and cross-check agreement, with reference lines from the original patent designs and baseline scores for several coding agents. |

Out of scope for v0.x: freeform surfaces, off-axis reflective systems, zoom lenses, end-to-end computational imaging.

Not compared across engines: Seidel and Zernike aberration coefficients, spot size and MTF. The engines normalize them differently, and RayOptics has no MTF, so a numeric comparison would report conventions rather than errors.

Zemax OpticStudio stays an optional backend through [ai-zemax-optical-design](https://github.com/Jerry-del975/ai-zemax-optical-design); CI never requires it.
