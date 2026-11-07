---
name: diagnose-optical-discrepancies
description: Explain why Optiland and RayOptics disagree on the same local Zemax .zmx sequential prescription. Compares the prescription each engine actually built (geometry, stop, wavelengths, glass catalog and index per surface, object distance), first-order EFL and working F-number, and real-ray image intercepts, then runs cumulative elimination experiments (glass-catalog swap, finite object distance, real ray aiming) and reports confirmed causes and open items. Use for 诊断/解释 两个引擎结果不一致, after cross-check-optical-designs returns MISMATCH, or when a reference and an engine disagree; not for a first check of a design (design-optical-systems, cross-check-optical-designs) or for editing designs.
---

# Diagnose Optical Discrepancies

Use this skill when two engines give different numbers for one `.zmx` file and the user wants to know why. The diagnosis explains the difference between the engines. It does not decide which engine is right; only a supplied reference (an OpticStudio export) can show which one matches it.

## Safety contract

- Accept only an absolute local `.zmx` path. Every probe hashes the source before and after and fails if it changed. Never save or edit the prescription.
- Write into a new or empty output directory. Refuse a non-empty one unless the user explicitly authorizes `--force`.
- Run each engine only in its own pinned environment. Do not install, upgrade or patch engine packages to make a probe pass.
- Report a cause as confirmed only when an experiment removed the difference. Report everything else as an unconfirmed input finding or as unresolved.

## Setup

The probes reuse the pinned environments of `design-optical-systems` (Optiland) and `cross-check-optical-designs` (RayOptics); install both from their `requirements.txt`. The diagnosis itself is standard library only and runs with any Python 3.10+. It finds the engine interpreters through `OPTICS_SKILLS_PYTHON_DESIGN` and `OPTICS_SKILLS_PYTHON_CROSSCHECK`, falling back to `<repo>/.venv-design-optical-systems` and `<repo>/.venv-cross-check-optical-designs`.

## Run

```bash
python <skill-dir>/scripts/diagnose.py --input-zmx /absolute/input.zmx --output-dir /absolute/new-dir --reference-json /absolute/opticstudio-reference.json
```

`--reference-json` is optional. It takes an OpticStudio reference in the format of the repository's `tests/data/*/*-native-reference.json` and adds a per-engine EFL agreement. If the user gives no output directory, use `<current working directory>/optics-diagnosis/<zmx stem>-<UTC yyyyMMddTHHmmssZ>/` and report it.

The output directory holds `diagnosis.json` and one `probe-*.json` per engine run. The command prints a one-line summary. The exit code is 0 for `AGREE` or `EXPLAINED`, 1 for `UNRESOLVED` and 2 for an input, safety or engine error.

## How it works

1. Probe both engines (schema `optics-probe/1`). Each probe records the surfaces it built (radius, thickness, material name and catalog, index at every wavelength), the stop, the wavelengths, the fields, the EFL, the working F-number from the paraxial marginal ray, and the image intercepts of the chief ray and three pupil-edge rays per field at the primary wavelength.
2. Compare the inputs, then the first-order values, then the rays. The tolerances are in `diagnosis.json` under `tolerances`.
3. Run experiments on Optiland only, holding RayOptics fixed. Each runs only while the difference it targets remains. A setting that removes a difference is kept for the next experiment; one that removes nothing is reverted:
   - `material_catalog_swap`: give Optiland the glass catalogs RayOptics resolved.
   - `object_distance`: place the object at RayOptics' finite distance. RayOptics stores an infinite object as 1e10 mm, which shifts the image by about f²/z. Skipped when the estimated edge-ray shift and working-F-number change are below tolerance.
   - `ray_aiming`: switch Optiland to iterative aiming at the real stop.
4. Credit each difference to the first experiment after which it disappears. A ray an experiment cannot trace (Optiland returns NaN for wide angle fields from a 1e10 mm object) keeps its earlier state and is listed under `untraced_rays`. Whatever remains after the last experiment is unresolved.

## Report fields (`optics-diagnosis/1`)

| Field | Meaning |
| --- | --- |
| `status` | Judged on output differences (first-order and rays): `AGREE` (none), `EXPLAINED` (experiments removed all of them) or `UNRESOLVED`. |
| `baseline` | Input, first-order and ray differences before any experiment. |
| `experiments` | Each experiment with its hypothesis, cumulative settings, status (`RAN` or `SKIPPED` with a reason) and the comparison after it. |
| `causes` | Confirmed causes only: the category, `confirmed_by` (the experiment) and `explains` (the differences it removed). |
| `input_differences_without_confirmed_effect` | Input differences (importer, catalog, object distance) that no experiment tied to an output difference. |
| `unresolved` | Differences no experiment removed, with the remaining candidates. |
| `reference` | Per-engine EFL against the supplied reference, or null. |
| `limitations` | Scope limits that apply to every run. |

## Reporting

State the status and each confirmed cause with its size (for example, the EFL before and after the experiment). Name the unresolved items plainly. Without a reference, do not say which engine is correct. When the reference agrees with one engine, say only that this engine matches the reference for that quantity.

## Known results on the bundled samples

| Sample | Status | Confirmed causes | Unresolved |
| --- | --- | --- | --- |
| Cooke triplet | `UNRESOLVED` | `material_catalog`: the ZMX declares `GCAT HIKARI SCHOTT`. RayOptics and OpticStudio take F2 from Hikari, Optiland from Schott; the swap moves the Optiland EFL from 49.999783 mm to 50.000394 mm, the RayOptics and OpticStudio value, and removes the F-number difference. `ray_aiming`: iterative aiming removes the chief-ray differences at 14° and 20°. | Six pupil-edge rays at 14° and 20°, up to 0.025 mm. |
| Double-Gauss | `UNRESOLVED` | `ray_aiming`: chief rays at 10° and 14°. Four glasses resolve to different catalogs; the swap removed nothing and was reverted. | Six pupil-edge rays at 10° and 14°, up to 0.0016 mm. |
| Hubble | `EXPLAINED` | `object_distance`: RayOptics puts the object at 1e10 mm, Optiland at infinity. With the same distance, the working F-number difference (4.8e-5 relative) and all six 6.9 µm edge-ray differences disappear; f²/z = 0.33 mm of defocus at F/24 predicts 6.9 µm. | None. |

These rows document the qualified runs. Verify them against a fresh `diagnosis.json` before quoting them for another runtime.

## Scope limits

Only Optiland and RayOptics are probed, and only sequential, rotationally symmetric prescriptions that both engines load. Aberration coefficients, spot size and MTF are not compared: the engines normalize them differently and RayOptics has no MTF. The marginal-ray candidates that remain open (pupil coordinate definitions, vignetting conventions) have no experiment yet.
