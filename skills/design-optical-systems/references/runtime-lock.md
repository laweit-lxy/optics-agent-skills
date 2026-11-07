# Optiland runtime lock

## Pinned runtime

- Repository: https://github.com/optiland/optiland (MIT).
- Release `0.6.3`, commit `bb487f9b56baaf82eaa563750ff351a5ce90d63d` (tag v0.6.3).
- PyPI wheel SHA-256: `65f5e284b1d61196160242c5753737760205c45a1f9e176d5ff51009f83c5483`.
- Installed code: 538 `.py`/`.pyi`/`.typed` files, manifest SHA-256 `f288c43ae5f75aa841e30029b5decf7740c6fd88b1bf37ddbbbc514165d912a1`. Every report recomputes the count and manifest; a mismatch blocks qualification.
- Python 3.12. NumPy 2.4.6, SciPy 1.18.0, Numba 0.66.0, VTK 9.6.2; the full set is in `requirements.txt`.
- Backend: NumPy CPU, explicitly selected. GUI and Torch extras are not qualified.

Install into a dedicated virtual environment:

```bash
python3.12 -m venv .venv-design-optical-systems
.venv-design-optical-systems/bin/python -m pip install -r requirements.txt   # Windows: .venv-design-optical-systems\Scripts\python.exe
```

## Process-local behavior

`NUMBA_DISABLE_JIT=1`, `MPLBACKEND=Agg` and a temporary Matplotlib configuration apply only inside the process. The pinned import stalled in Numba JIT initialization on the Windows host where it was first qualified; the Cooke sequential analyses do not use the scatter/NURBS JIT paths. Scatter/NURBS JIT performance, GUI, GPU/Torch, stray light, coatings, optomechanics, and arbitrary commercial-file coverage remain unqualified.

## Qualification

- The self-test passes all 22 required checks; 2 known non-blocking findings stay visible.
- Cooke prescription, EFL/F-number, spot arrays, OPD, PSF/MTF, deterministic three-point sensitivity and restoration, JSON equality, and surface-group ABCD composition pass.
- Hubble and Double-Gauss ZMX round trips keep paraxial `rtol=1e-12` and ray-intercept `atol=1e-9` gates. Cooke catalog identity, actual n(λ), EFL, and binary64 formatting gates pass.
- Immutable Hubble OpticStudio 2023 R1.02 references for first-order quantities, six real rays, and spot radii pass unchanged.
- Hubble RMS wavefront sampling leaves a residual near 0.00076 waves; strict tangential field curvature remains an upstream xfail boundary (0.6%). Both are accepted as non-blocking; neither threshold is relaxed. Re-evaluate at the next Optiland upgrade; an unexpected pass is a behavior change to investigate.
- Known reference, not a gate: on `tests/data/cooke/cooke-6cd4da4.zmx`, Optiland EFL is 49.999783 mm against OpticStudio 50.000394 mm, a relative difference of -1.22e-5, slightly above `RTOL=1e-5`. The cause is not investigated (glass data suspected).

The v0.6.3 release precedes later upstream GCAT/F-number fixes; do not attribute those fixes to this release.

## Changing the pin

Any change to the Optiland version, dependencies, reference constants or tolerances requires rerunning the repository test suite and updating the manifest constants in `scripts/optiland_regression.py` together with this file. Independent OpticStudio constants must never be regenerated from Optiland.
