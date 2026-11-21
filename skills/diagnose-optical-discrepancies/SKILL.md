---
name: diagnose-optical-discrepancies
description: Explain why Optiland and RayOptics disagree on the same local Zemax .zmx sequential prescription. Compares the prescription each engine actually built (geometry, stop, wavelengths, glass catalog and index per surface, object distance), first-order EFL and working F-number, and real-ray image intercepts, then runs cumulative elimination experiments for glass catalogs, object distance, ray aiming, field vignetting and pupil coordinates and reports confirmed causes and open items. Use for 诊断/解释 两个引擎结果不一致, after cross-check-optical-designs returns MISMATCH, or when a reference and an engine disagree; not for a first check of a design (design-optical-systems, cross-check-optical-designs) or for editing designs.
---

# Diagnose Optical Discrepancies

Use this skill when two engines give different numbers for one `.zmx` file and the user wants to know why. The diagnosis explains the difference between the engines. It does not decide which engine is right; only a supplied reference (an OpticStudio export) can show which one matches it.

## Safety contract

- Accept only an absolute local `.zmx` path. Every probe hashes the source before and after and fails if it changed, and the diagnosis checks the hash again after writing its report. Never save or edit the prescription.
- Write into a new or empty output directory. Refuse a non-empty one unless the user explicitly authorizes `--force`. Even with `--force`, an output file that is a link or hard link of the prescription or the reference is refused.
- Run each engine only in its own pinned environment. Both probes refuse an engine that fails its pinned source check and record the check under `engines.<engine>.integrity`. Do not install, upgrade or patch engine packages to make a probe pass.
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

1. Probe both engines (schema `optics-probe/1`). Each probe records the surfaces it built (radius, thickness, material name and catalog, index at every wavelength), the stop, the wavelengths, the fields, the EFL, the working F-number from the paraxial marginal ray, and the image intercepts of the chief ray and three pupil-edge rays per field at the primary wavelength. The RayOptics probe converts lengths and height fields from the file's unit to mm. The probes record each ray's `effective_pupil` after field vignetting and `stop_xy_mm` for centered systems.
2. Check that both reports are complete, then compare the inputs, the first-order values and the rays. The tolerances are in `diagnosis.json` under `tolerances`. If the engines built a different number of surfaces, different wavelengths or primary wavelength, or different fields, the outputs do not describe the same rays: no experiment runs and the status is `UNRESOLVED` with a `not_comparable` item.
3. Run experiments on Optiland only, holding RayOptics fixed. Each runs only while the difference it targets remains. A setting that removes a difference is kept for the next experiment; one that removes nothing is reverted:
   - `material_catalog_swap`: give Optiland the glass catalogs RayOptics resolved.
   - `object_distance`: place the object at RayOptics' finite distance. The pinned RayOptics replaces an infinite object with a finite distance chosen for about 1 nm of image shift (f²/z), clamped to 1e10–1e20 in the file's length unit: 1e10 mm for Cooke, about 3.3e15 mm for Hubble. Skipped when the estimated edge-ray shift and working-F-number change are below tolerance.
   - `ray_aiming`: switch Optiland to iterative aiming at the real stop.
   - `vignetting`: substitute the effective normalized pupil coordinates RayOptics actually used after its field factors. Keep the current Optiland aimer. On identical maps this is a no-effect control. It does not test clipping by physical apertures or throughput.
   - `pupil_coordinates`: keep the iterative aimer and the effective vignetted pupil fixed. For remaining traced edge rays with matching effective coordinates and centered geometry through the same stop, aim Optiland at RayOptics' actual local stop intercept instead of interpreting the normalized pupil as a point on the stop. Record the target and achieved stop coordinates; a ray that fails to reach the target within the aimer's tolerance is untraced for the trial.
4. Credit each difference to the first experiment after which it disappears. A ray an experiment cannot trace is listed under `untraced_rays` and never credited (at a 1e10 mm object, Optiland returns NaN for some Cooke fields and for every Double-Gauss field, the axis included). A ray that had a difference keeps it; a ray that agreed before becomes an `untraced_ray` item if the experiment is kept. A ray missing from one report counts as untraced. Whatever remains after the last experiment is unresolved.

## Report fields (`optics-diagnosis/1`)

| Field | Meaning |
| --- | --- |
| `status` | Judged on output differences (first-order and rays): `AGREE` (none), `EXPLAINED` (experiments removed all of them) or `UNRESOLVED`. |
| `baseline` | Input, first-order and ray differences before any experiment. |
| `surface_comparison` | Both baseline imports by surface index: vertex curvature (1/mm), thickness of the following gap (mm), glass name/catalog and refractive indices in the listed wavelength order. `delta` is Optiland minus RayOptics; unavailable differences are null, including index deltas when wavelength grids differ. When surface indices do not align, read the raw columns only. |
| `experiments` | Each experiment with its hypothesis, cumulative settings, status (`RAN` or `SKIPPED` with a reason) and the comparison after it. |
| `causes` | Confirmed causes only: the category, `confirmed_by` (the experiment) and `explains` (the differences it removed). |
| `input_differences_without_confirmed_effect` | Input differences (importer, catalog, object distance) that no experiment tied to an output difference. |
| `unresolved` | Items that block `EXPLAINED`: `first_order` and `real_ray` differences no experiment removed, `untraced_ray` (no valid intercept in one engine under the final settings) and `not_comparable` (different surfaces, wavelengths or fields). |
| `reference` | Per-engine EFL against the supplied reference, or null. |
| `limitations` | Scope limits that apply to every run. |

## Reporting

State the status and each confirmed cause with its size. For a pupil-coordinate cause, use the `probe-optiland-*.json` and `probe-rayoptics.json` files to report the edge-ray image residual before and after matching, in mm. Distinguish the measured change from the `1e-4` mm diagnosis threshold. Name the unresolved items plainly. Without a reference, do not say which engine is correct. When the reference agrees with one engine, say only that this engine matches the reference for that quantity.

## Known results on the bundled samples

| Sample | Status | Confirmed causes | Unresolved |
| --- | --- | --- | --- |
| Cooke triplet | `EXPLAINED` | `material_catalog`: Hikari F2 moves EFL from 49.999783 mm to 50.000394 mm and removes the F-number difference. `ray_aiming`: iterative aiming removes the chief-ray differences at 14° and 20°. `pupil_coordinates`: matching actual stop intercepts reduces the maximum of six edge-ray differences from 0.024685 mm to about 2.7e-8 mm. | None above tolerance. |
| Double-Gauss | `EXPLAINED` | `ray_aiming`: chief rays at 10° and 14°. `pupil_coordinates`: the maximum of six edge-ray differences drops from 0.001588 mm to about 1.1e-7 mm. Four glass catalog labels differ but their sampled refractive indices agree; the swap removed nothing and was reverted. | None above tolerance. |
| Hubble | `AGREE` | None. RayOptics puts the object at about 3.3e15 mm, Optiland at infinity; this remains an input difference, and `object_distance` is skipped because its estimated effect is 2.1e-8 mm on edge rays and 1.7e-11 relative on the working F-number. Both engines match the reference EFL. | None. |

Cooke and Double-Gauss use identical effective pupil coordinates after field vignetting; the vignetting trial did not change their residuals. Verify these results against a fresh `diagnosis.json` and its probes before quoting them for another runtime.

## Scope limits

Only Optiland and RayOptics are probed, and only sequential, rotationally symmetric prescriptions that both engines load. Aberration coefficients, spot size and MTF are not compared: the engines normalize them differently and RayOptics has no MTF. The pupil-coordinate trial needs a shared centered stop, retained iterative aiming and matching field vignetting for the rays it tests. A skipped trial does not resolve the difference. The comparison is of ray intercepts, not transmission, and does not judge which engine uses the correct pupil convention.
