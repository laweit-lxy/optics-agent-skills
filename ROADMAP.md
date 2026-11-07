# Roadmap

A release every two weeks. Each release must keep the regression suite green on Linux and Windows.

| Version | Target | Scope |
| --- | --- | --- |
| v0.1.0 | 2026-11-20 | `design-optical-systems` (Optiland) and `cross-check-optical-designs` (RayOptics); portable pinned environments; Cooke, Double-Gauss and Hubble regressions against OpticStudio references; CI; Claude Code plugin and Codex install. |
| v0.2 | 2026-12-04 | `analyze-optical-designs` (Prysm/Chromatix wave optics). Discrepancy diagnosis: compare real rays, aberration coefficients, spot and MTF across engines, and run elimination experiments (glass catalog, aperture convention, surface-by-surface import) on `MISMATCH`. Shared core package and a FastMCP server over it. |
| v0.3 | 2026-12-18 | `process-radiometric-calibration` (SRF convolution, TOA reflectance, MC/GUM uncertainty). Starting-point library of classic lens forms from expired patents and public literature, each with its source. |
| v0.4 | 2027-01-01 | Requirements-to-lens design loop: pick a starting form, optimize with Optiland (including the differentiable Torch backend), run Monte Carlo tolerancing and yield, then verify independently with the cross-check engines. Scope: rotationally symmetric spherical and aspheric systems, visible and near infrared. |
| v0.5 | 2027-01-15 | `optics-bench`: 20–30 lens design tasks scored on requirement attainment, cost (element count, length) and cross-check agreement, with reference lines from the original patent designs and baseline scores for several coding agents. |

Out of scope for v0.x: freeform surfaces, off-axis reflective systems, zoom lenses, end-to-end computational imaging.

Zemax OpticStudio stays an optional backend through [ai-zemax-optical-design](https://github.com/Jerry-del975/ai-zemax-optical-design); CI never requires it.
