---
name: process-radiometric-calibration
description: Convolve a local spectral radiance table with a band spectral response function (SRF/RSR), then calculate top-of-atmosphere (TOA) reflectance and compare GUM and Monte Carlo uncertainty. Use for Landsat/Sentinel-style two-column SRF tables or a custom spectrometer's band response. Not for DN-to-radiance conversion, atmospheric correction, or pixel-to-wavelength calibration.
---

# Process Radiometric Calibration

1. Read `references/input-schema.md`. Use one band per JSON input, with explicit wavelength and spectral-density units. Check the source metadata for a common wavelength medium; the CLI only records the supplied declaration. For TOA, use the acquisition date, solar zenith (not elevation) and either a solar spectrum or a band-averaged solar irradiance, both at 1 au.
2. Use the dedicated Python environment in `references/runtime-lock.md`. Supply an absolute input path and a new absolute output directory with an existing parent. The tool opens the input JSON and CSV files read-only and refuses URLs, UNC paths, symlinks and reparse points.
3. Run the CLI and read `report.json`. Require `status=PASS` and matching before/after SHA-256 hashes for all inputs. Coverage failures name the missing range: supply a spectrum covering the full SRF support rather than truncating or extrapolating. On `FAIL`, `result` is null.
4. Report SRF support and band radiance in the canonical units. For TOA also report the irradiance source, day of year, approximate Earth–Sun distance, zenith, and dimensionless reflectance. Read warnings before using values outside [0, 1].
5. When uncertainty is supplied, report the GUM estimate and standard uncertainty, the Monte Carlo mean, standard uncertainty and equal-tail 95% interval, and the comparison verdict. For `DISAGREE`, keep both results and investigate the listed causes before choosing a reported uncertainty. Read `references/methods-and-sources.md` for thresholds and model limits. If uncertainties were not supplied, report them as not evaluated.

## Run

`<python>` is the pinned interpreter; `<skill-dir>` is the absolute path to this skill. The example is synthetic.

```bash
<python> -X utf8 -I <skill-dir>/scripts/process.py --input <skill-dir>/examples/input.json --output-dir /absolute/new-output-dir
```

Use `scripts/contract.py --output-dir <absolute-new-directory>` to qualify the runtime without processing input. Use `tests/regression.py --output-dir <absolute-new-directory>` to run the analytic regressions in fresh CLI processes with the same interpreter and flags.
