# RASCAL runtime lock

## Pinned runtime

- Repository: https://github.com/jveitchmichaelis/rascal (BSD-3-Clause).
- Release `0.3.11` from PyPI. Python 3.12, 64-bit. NumPy 2.5.4, SciPy 1.18.1; the full set of 21 distributions is in `requirements.txt`.
- The lock pins versions, not wheel hashes. Library source is used unmodified.
- CPU only. Matplotlib is forced to the Agg backend with a cache inside the new output directory; nothing is plotted and no browser is started (Kaleido is installed as a RASCAL dependency and never called).

Install into a dedicated virtual environment:

```bash
python3.12 -m venv .venv-calibrate-spectral-wavelength
.venv-calibrate-spectral-wavelength/bin/python -m pip install -r requirements.txt   # Windows: .venv-calibrate-spectral-wavelength\Scripts\python.exe
```

## Runtime gate

`references/runtime.json` lists the modules that must import. `scripts/contract.py` requires isolated UTF-8 mode (`-X utf8 -I`), 64-bit Python 3.12 and every distribution in `requirements.txt` at its pinned version, then imports the engine. Every calibration runs this gate first and fails without fitting when it does not pass. Distributions outside the lock (pip, a test runner) are listed in the report as `unpinned_distributions` and do not fail the gate.

## Library behavior the script works around

- `Calibrator` infers a pixel axis from the peaks when it gets neither a spectrum nor `num_pix`, and setting `num_pix` later keeps that inferred axis. The script always sets `num_pix` and the complete `pixel_list` together and verifies them. The two constructor warnings about the inferred axis are expected.
- `load_calibration_lines(min_distance=...)` removes every member of a close group of lines instead of keeping one. The script passes `min_distance=0` and offers its own strongest-per-bin selection.
- `load_calibration_lines(vacuum=True)` returns vacuum wavelengths, while `Atlas.add_user_atlas(vacuum=True)` converts the given vacuum values to air. Custom lines are inserted with `vacuum=False` so they stay in the declared medium.
- `_get_most_common_candidates` sorts on unique wavelengths but indexes the array that still holds duplicates, so a candidate can be dropped. The installed code is left as it is; the script rejects duplicate or ambiguous assignments in the returned fit.
- The upstream Quickstart calls `refine_peaks(peaks)`, `add_atlas(...)` and `fit(polydeg=...)`. Version 0.3.11 needs `refine_peaks(spectrum, peaks, ...)`, deprecates `add_atlas` in favor of `Atlas` with `set_atlas`, and names the argument `fit_deg`.
- The bundled NIST line file has SHA-256 `21e2a8426db766a4b5b1f0dbf8e440205e0b4a05530f505eccb4a74624d7b3c3`; the report records the hash of the file it used.

## Qualification

`tests/regression.py` runs the command line in fresh processes on a synthetic Hg/Ar/Ne spectrum (400 to 700 nm, 1301 pixels, about 0.23 nm/pixel, 0.15 pixel noise, 3 false peaks, 6 holdout lines) for four seeds. Thresholds: fit RMS and holdout RMS at most 0.10 nm, holdout maximum error at most 0.20 nm, no wrong assignment. It also covers the lamp-atlas and custom-vacuum branches, holdout isolation and two failure paths. First qualified on Windows 11 (x64 Python 3.12.14): all four seeds passed with holdout RMS between 0.018 and 0.034 nm.

Real lamp spectra, peak finding, blended lines and polynomial degrees other than 2 are not qualified.

## Changing the pin

A change to the RASCAL version or any dependency requires rerunning `tests/regression.py` and updating the reference values in it together with this file.
