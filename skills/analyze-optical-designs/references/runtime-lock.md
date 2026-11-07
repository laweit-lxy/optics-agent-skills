# Chromatix / Prysm runtime lock

## Pinned runtime

- Chromatix 0.6.0 from `chromatix-team/chromatix@ce1482906fc663298613bb252bbf425e3be59839` (MIT).
- Prysm 0.22 from `brandondube/prysm@5008f47803af6ff69eed474fca049456076e4a7d` (MIT).
- Python 3.12; JAX/JAXLIB 0.11.0, NumPy 2.5.1, SciPy 1.18.0. `requirements.txt` locks every distribution except pip.
- JAX backend: CPU.

Install into a dedicated environment (Git is required for the pinned sources); never upgrade an existing environment in place:

```bash
python3.12 -m venv .venv-analyze-optical-designs
.venv-analyze-optical-designs/bin/python -m pip install -r requirements.txt   # Windows: .venv-analyze-optical-designs\Scripts\python.exe
```

## Self-test

`scripts/optics_regression.py --self-test` exits 0 with `passed: true` only when:

- the installed Chromatix and Prysm commits match the pins above;
- the installed distributions equal `requirements.txt` (missing, extra or different versions fail; pytest and its helpers are reported under `ignored_test_tooling`);
- Chromatix normalizes a plane wave to unit power within 1e-6 and conserves it through a far-field lens within 1e-5 relative. This check runs in float64 (`jax.enable_x64`): in float32 the power sum depends on the CPU's reduction order (GitHub runners measured 7.2e-6), which made the result machine-dependent;
- Prysm conserves energy through `focus` within 1e-12 relative and the MTF is 1 at zero frequency;
- a JAX gradient of the focal-spot energy fraction agrees with a central difference within 1e-3 relative;
- the Prysm MTF of a sampled circular pupil matches the analytic diffraction-limited MTF at 0.25, 0.5 and 0.75 of cutoff within 2e-3 absolute.

First qualified 2026-11-04 on Windows x64: Chromatix relative power error 5.96e-7 (float32; 2.2e-16 in float64 since 2026-11-07); Prysm relative energy error 1.4e-16; gradient vs central difference 1.37e-5; analytic MTF max absolute error 6.9e-4.

## Changing a pin

Before changing a pin, read upstream release notes, license, tests, supported Python/JAX versions and wheels for Linux and Windows. Run the self-test before and after the update, regenerate `requirements.txt` with `pip freeze` (exclude pip), and rerun the repository test suite.
