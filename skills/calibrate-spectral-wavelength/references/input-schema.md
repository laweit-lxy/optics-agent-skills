# Input and output contract

All numerical wavelengths are nm, pixels are zero-based. Unknown fields and nonfinite values are rejected. Input is one ordinary local absolute-path JSON file, read-only; no external input files are opened through JSON fields.

## Required input

| Field | Contract |
|---|---|
| `peaks_pixel` | Nonempty list of distinct finite pixel positions, each in `[0,num_pixels-1]`. Order is retained through `input_index`; fitting uses ascending positions. At least `max(10,degree+3)` training peaks after holdout exclusion. |
| `num_pixels` | Integer 2–10000000; a contiguous complete detector grid `arange(num_pixels)` is constructed. Gapped/mosaic axes are outside scope. |
| `wavelength_range_nm` | `[min,max]`, positive and increasing, detector endpoint coverage estimate. Increasing dispersion only. |
| `wavelength_medium` | `air` or `vacuum`, applies to the range, custom atlas and holdout truth together. |
| `atlas` | Exactly one of the two forms below. At least `max(10,degree+3)` distinct in-band wavelengths must remain after selection and holdout removal. |
| `polynomial_degree` | Integer 1–5. Power basis. Quadratic is the regression-qualified case. |
| `seed` | Integer 0–4294967295, explicitly passed to RASCAL's random generator. |
| `max_chord_deviation_nm` | Nonnegative bound on the expected nonlinear mapping's maximum deviation from the straight endpoint chord. Supply instrument evidence; range alone cannot determine this. Candidate half-window=`max(0.10,1.25*bound)` nm, Hough linearity tolerance=`max(3,1.5*bound)` nm. Baseline bound 2 nm gives 2.5 nm/3 nm. |

Custom atlas: `{"lines":[{"wavelength_nm":404.656,"element":"Hg","relative_intensity":1}, ...]}`. Each row requires `wavelength_nm`; optional `element` defaults to `custom`, nonnegative `relative_intensity` defaults to 1. Values are already in the declared medium; no conversion. Out-of-band lines are discarded, exact duplicate wavelengths retain the strongest row.

Lamp atlas: `{"elements":["Hg","Ar","Ne"],"min_intensity":10}`. Chemical symbols select the bundled NIST table; `min_intensity` is nonnegative and defaults to 10. Library `min_distance=0` prevents deletion of entire close-line groups. Optional `selection:{"bin_width_nm":10,"min_separation_nm":2}` takes the strongest eligible line in each bin starting at the requested band minimum and requires its distance from previously selected lines to be at least the separation. Bin width is positive, separation nonnegative. This is a caller-selected sparse atlas policy, not automatic identification of which lines a real lamp emits. Without selection all loaded in-band lines are retained except exact wavelength duplicates. The report records line-table hash and exact used lines.

## Optional input

| Field | Contract |
|---|---|
| `peak_sigma_pixel` | Positive finite list with exactly one standard uncertainty per input peak. Reported and propagated locally by `abs(dlambda/dpixel)*sigma`; does not weight RANSAC. |
| `holdout_lines` | List of `{"pixel":...,"wavelength_nm":...,"sigma_pixel":...}`; sigma optional and positive. Pixels/values must lie in detector/band; holdout pixels and wavelengths must each be distinct. Pixels within 1e-8 pixel of holdouts are excluded from training, atlas wavelengths within 1e-7 nm are excluded. The caller supplies independently known identities. |
| `air_conditions` | Complete object `{"temperature_K":273.15,"pressure_Pa":101325,"relative_humidity_percent":0}`. These are defaults when omitted. Temperature/pressure positive, humidity 0–100%. Used only for built-in NIST conversion to air; custom and vacuum values remain unchanged. |

No source polynomial or known matching anchors enter the fit. Holdout wavelengths enter only exclusion and subsequent error calculation.

## Output

`report.json` includes `schema_version`, `status`, runtime versions/interpreter checks, input SHA-256 before/after, `settings`, exact used atlas, per-input `peaks`, fit RMS, utilisation, holdout predictions/errors and `checks`. Peaks are `MATCHED`, `REJECTED` or `EXCLUDED_HOLDOUT`; residual is predicted minus assigned wavelength. Holdout error is predicted minus supplied independent truth.

`polynomial` exists as a usable object only for PASS; it contains basis, coefficient order, detector domain, medium and one `{power,value,unit}` per coefficient. Every failure sets it to null. Input/fit exceptions produce `error` and `failure.log`; completed fits that fail acceptance retain metrics and failed check names. No physical identity error count is claimed for unknown data: the regression alone can count wrong matches using synthetic truth.

Exit 0: PASS. Exit 1: runtime/input/fit/acceptance failed, with report. Exit 2: output/path refusal or CLI usage, with stderr. No overwrite option. A failed output directory remains evidence; use a new directory for retries.
