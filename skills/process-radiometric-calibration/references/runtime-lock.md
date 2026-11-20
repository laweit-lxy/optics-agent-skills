# Radiometric calibration runtime lock

- Python 3.12, 64-bit, CPU only. `requirements.txt` pins NumPy 2.5.4, the sole third-party runtime dependency ([NumPy license](https://numpy.org/doc/stable/license.html), BSD-3-Clause core and bundled components as documented there). No wheel hashes are pinned.
- The numerical model uses explicit conversions for the supported units and analytic GUM derivatives. It does not depend on a global Pint registry or on uncertainty-package defaults.
- Use an isolated virtual environment (a separate copy of the Python packages just for this skill). From the repository root:

```bash
python3.12 -m venv .venv-process-radiometric-calibration
```

```bash
.venv-process-radiometric-calibration/bin/python -m pip install -r skills/process-radiometric-calibration/requirements.txt
```

On Windows, use your Python 3.12 interpreter in the first command and `.venv-process-radiometric-calibration/Scripts/python.exe` in the second. Add `pytest` only if running the repository test entry.

Run skill scripts with `-X utf8 -I`. Every processing run checks the 64-bit Python minor version and flags, exact required distribution versions, and imports listed in `runtime.json` before processing. Extra distributions (e.g. pip or pytest) are recorded and do not fail the gate. `scripts/contract.py --output-dir <absolute-new-directory>` reports the same checks without an input file.

The [skill regression script](../tests/regression.py) runs the actual CLI in fresh processes for analytic SRF and TOA cases, a linear uncertainty match and a deliberately nonlinear disagreement. The [repository test entry](../../../tests/test_process_radiometric_calibration.py) runs it in the Linux and Windows CI matrix and checks the runtime and no-overwrite gates. Re-run the regression and update this lock when changing a pin. Qualification uses synthetic cases, not an instrument-specific calibration dataset.
