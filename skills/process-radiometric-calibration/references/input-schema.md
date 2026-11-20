# Radiometric calibration input

Supply one UTF-8 JSON object; see `../examples/input.json` for an executable example. The schema rejects unknown and duplicate fields, nonfinite numbers, and boolean values in numeric fields. Inputs are local regular files (at most 16 MiB each) with `.json` and `.csv` suffixes, case insensitive. The CLI takes absolute JSON and output paths. CSV paths may be absolute or relative to the JSON directory, with no `..` segments. An existing output path, even an empty directory, is refused.

## Tables

| JSON field | Required fields in the table descriptor | Default CSV headers |
|---|---|---|
| `srf` | `csv`, `wavelength_unit` | `wavelength,response` |
| `radiance` | `csv`, `wavelength_unit`, `value_unit` | `wavelength,value` |
| `toa.solar_spectrum` | `csv`, `wavelength_unit`, `value_unit` | `wavelength,value` |

- Set root `wavelength_medium` to `air` or `vacuum` after checking all input tables. This is a shared declaration, not an air/vacuum conversion.
- Export one band from a mission SRF/RSR table to a comma-delimited UTF-8 CSV (BOM accepted) with two named columns. For different headers, add `columns: ["wavelength header", "data header"]` to that descriptor. The physical column order may differ. Provide one column of positive, strictly increasing wavelengths and at least two data rows. The limit is 200,000 rows per CSV. No row reordering, merging duplicates or filling missing values occurs.
- Set `wavelength_unit` to `nm`, `um` or `µm`. The wavelength coordinate and `value_unit` are independent. For radiance use `W/m^2/sr/nm` or `W/m^2/sr/um`; for irradiance use `W/m^2/nm` or `W/m^2/um` (`µm` is accepted in either density unit). Values per nm are multiplied by 1,000 to report per µm. Wavelengths are positive; radiance may be signed. Irradiance and relative response values must be nonnegative. SRF values may be fractional or percentage-scale numbers; only their relative weights matter. The SRF must have positive integrated area.
- Tabulated values are piecewise linear. Each spectrum must cover the SRF from the first nonzero knot (including its adjacent zero shoulder if present) to the last nonzero knot (including its adjacent zero shoulder). Zero-only padding beyond those shoulders does not require spectral coverage. Beyond the tabulated SRF endpoints the response is taken as zero, even when an endpoint is nonzero; retain measured zero shoulders when available. No valid partial-coverage result is returned.

## Optional `toa` object

Omit `toa` to calculate only the band radiance. Otherwise supply `acquisition_date` (`YYYY-MM-DD`) and `solar_zenith_deg` (0 inclusive to 90 exclusive); if metadata provides solar elevation, subtract it from 90°. Supply exactly one of `solar_spectrum` or `band_solar_irradiance`. Both branches require irradiance referenced to 1 au; the band result must be strictly positive. `band_solar_irradiance` accepts e.g. `{"value": 1.6, "value_unit": "W/m^2/nm"}`. Supply an SRF-weighted spectral density, not a band-integrated value in W/m² or an irradiance already corrected for acquisition distance.

For `toa.uncertainty`, set `inputs` to at least one of the variables below. Each supplied variable has `standard_uncertainty` (a positive standard deviation) and `distribution`. Omitting a variable treats its value as fixed in the measurement model.

| Variable | Unit for `standard_uncertainty` | Distribution |
|---|---|---|
| `band_radiance` | `W/m^2/sr/um` | `normal` or `rectangular` |
| `band_solar_irradiance` | `W/m^2/um` | `rectangular` |
| `earth_sun_distance_au` | `au` | `rectangular` |
| `solar_zenith_deg` | `deg` | `rectangular` |

Use the listed units even when the CSVs or direct irradiance use per-nm values. Convert expanded uncertainty `U` to `U/k` using the source's coverage factor. A rectangular half-width `a` becomes `a/sqrt(3)`. The full rectangular support must be strictly positive for irradiance and distance and entirely in [0, 90) for zenith; the program does not clip or discard draws to fit the model domain. Supply uncertainties only when the independent input models in `methods-and-sources.md` are appropriate. Optional `samples` (integer 10,000 to 1,000,000, default 100,000) and `seed` (integer 0 to 2³²−1, default 0) make the Monte Carlo check reproducible.

## CLI exits

- `0`: a `PASS` report with a result. If uncertainty was requested, inspect the `toa.uncertainty.comparison` verdict separately; `DISAGREE` preserves diagnostic results.
- `1`: a `FAIL` report with no result. Correct the runtime or the input using the error in the report.
- `2`: invalid command line or output path; an existing output is unchanged.
