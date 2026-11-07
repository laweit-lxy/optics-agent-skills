---
name: cross-check-optical-designs
description: Read-only third-engine check of a local Zemax .zmx sequential prescription with a pinned RayOptics runtime, comparing paraxial EFL/F-number and centered on-axis real-ray working F-number against an existing Optiland or OpticStudio JSON report, and auditing surfaces, stop, fields, wavelengths and glass/catalog resolution. Use for 交叉验证/复核 ZMX, or when EFL/F 数 disagree between engines; not for spot or aberration metrics (design-optical-systems), PSF/MTF or wave optics (analyze-optical-designs), or editing/optimizing designs in OpticStudio (ai-zemax-optical-design).
---

# Cross-check Optical Designs

Use this skill as an independent discrepancy detector for a local `.zmx` file. It does not establish RayOptics as ground truth and does not replace OpticStudio, Optiland, or `design-optical-systems` qualification.

This skill only consumes reference JSON that already exists. It does not run `design-optical-systems`, `analyze-optical-designs` or OpticStudio itself. When the result is `MISMATCH`, report the lead and let the user choose which tool investigates it.

## Safety contract

- Accept only an absolute local `.zmx` path. Reject URLs, UNC paths, symlinks, and reparse points.
- Hash the source before and after inspection. Never save, optimize, or overwrite the source prescription.
- Write one new JSON report. Refuse existing outputs unless the user explicitly authorizes `--force`.
- Keep the RayOptics source pinned, and the RefractiveIndex.INFO snapshot too when one is configured. Stop if an integrity gate fails.
- Treat `MISMATCH` as an investigation lead, not proof that either engine is wrong.

## Workflow

1. Verify the input path and analysis goal from the request and available files. Ask only when multiple inputs or goals cannot be reliably distinguished.
2. Choose the output path. If the user gave none, create `<current working directory>/rayoptics-crosscheck/` if needed and write `<zmx stem>-<UTC yyyyMMddTHHmmssZ>.json` there; never write into the source prescription's directory unless the user asks. The entry does not create parent directories. Report the chosen path.
3. Decide whether this is inspection-only or a comparison against a trusted reference JSON.
4. Run the entry below with the pinned environment's interpreter only.
5. Read the report fields in the table below. Required unavailable metrics or a wavelength mismatch fail; never suppress a requested F-number comparison.
6. Report the exact source hash, the status, the tolerances actually used, and classify any difference as prescription, material catalog, importer, or convention evidence that still needs investigation.

## Setup

Install the pinned environment once from this skill's `requirements.txt` (see `references/runtime-lock.md`). Below, `<python>` is that environment's interpreter and `<skill-dir>` is this skill's folder.

## Run an inspection

```bash
<python> <skill-dir>/scripts/rayoptics_crosscheck.py --input-zmx /absolute/input.zmx --output /absolute/new-rayoptics-report.json
```

`INSPECTED` requires the pinned runtime, any configured material snapshot, unchanged source, prescription load, and finite first-order checks to pass.

## Compare with Optiland or OpticStudio

Pass a JSON produced by `design-optical-systems` or an OpticStudio reference export (the repository's `tests/data/*/*-native-reference.json` show the format):

```bash
<python> <skill-dir>/scripts/rayoptics_crosscheck.py --input-zmx /absolute/input.zmx --reference-json /absolute/reference-report.json --output /absolute/new-crosscheck-report.json
```

Interpret the exit and report status together:

- `PASS` / exit 0: all integrity gates pass and every available EFL/F-number comparison is within tolerance.
- `INSPECTED` / exit 0: read-only inspection passed but no reference was supplied.
- `MISMATCH` / exit 1: only the reference comparison failed; preserve the evidence and investigate.
- `FAIL` / exit 1: a runtime, source, load, or finite-metric gate failed.
- Input/safety error / exit 2: correct the request or paths; do not bypass the boundary silently.

## Tolerances

The defaults are relative 1e-4 and absolute 1e-8. They are the qualified thresholds for the three reference samples; Hubble's F-number residual is about 4.8e-5 relative, so there is little margin. Pass `--relative-tolerance` or `--absolute-tolerance` only when the user explicitly asks for different values, and always state the values used (`comparison.relative_tolerance`, `comparison.absolute_tolerance`) in the reply. Never loosen a tolerance to turn `MISMATCH` into `PASS`.

## Report fields (schema 2.0)

| Field | Meaning |
| --- | --- |
| `status` | `PASS`, `INSPECTED`, `MISMATCH` or `FAIL`; read with the exit code. |
| `checks`, `failed_checks` | Integrity, source-hash, load and finite-metric gates, and the names of any that failed. |
| `model.catalog_resolution` | Per-surface glass name, declared GCAT catalog and resolved catalog. |
| `model.metric_definitions` | How each compared quantity is defined. |
| `model.working_f_number_analysis` | Real-ray working F-number result, or why it is unavailable. |
| `comparison` | Per-metric values, differences and tolerances used. |
| `limitations` | Scope limits that apply to this run. |

Native `working_f_number` (WFNO) compares to the RayOptics real-ray working F-number; native `paraxial_f_number` (ISFN) compares to paraxial fno. Optiland `f_number` keeps its paraxial comparison. The legacy paraxial `fno` field is retained.

## Catalog and comparison rules

- Named glass lookup uses the declared GCAT catalogs in order and exact glass names. Missing or unresolved named glasses fail; do not search unrelated catalogs or replace them with an nd/Vd model. Explicit MIRROR, ___BLANK and numeric-glass records keep the original parser path.
- The entry verifies the installed RayOptics commit (or package manifest) and, when configured, the material snapshot before importing the engine, and records the policy digest. Do not modify installed packages or refresh a configured material database.
- Real working F-number is qualified for centered on-axis analysis only: chief ray plus four vignetted pupil-edge rays, ignoring surface apertures as in the native WFNO definition. Unsupported geometry is reported as unavailable and cannot satisfy a required WFNO comparison.

## Scope limits

The adapter exposes surface/gap structure, stop, fields, wavelengths, audited media/catalog labels, paraxial first-order quantities, and centered on-axis real-ray working F-number. It does not expose optimization, prescription edits, file saves, spot diagrams, ray fans, PSF/MTF, wavefront, diffraction, tolerancing, or stray light. RayOptics' upstream documentation states that its author cannot verify Zemax imports against Zemax, so the repository regressions remain mandatory.

Read [references/runtime-lock.md](references/runtime-lock.md) for provenance, regression samples and rollback, and before changing the pin, dependencies, material snapshot, Windows path shim, tolerances, or accepted report schemas.
