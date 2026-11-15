---
name: build-optomechanical-parts
description: Build nominal rectangular aperture mounts and internally baffled cylindrical tubes from JSON dimensions in mm with pinned CadQuery 2.8.0; export STEP/STL and report analytic volume checks, B-rep validity, STEP roundtrip errors and explicit rigid assembly pose readback. Use for parameterized optomechanical CAD or CadQuery qualification; not tolerances, threads, collision checks, optical-prescription pose extraction, lens analysis (design-optical-systems), or OpticStudio design (ai-zemax-optical-design).
---

# Build Optomechanical Parts

## Workflow

1. Read `references/input-schema.md`. Prepare one JSON file containing nominal dimensions and optionally one explicit rigid pose per part. Use caller-provided dimensions/poses; substantive changes to an actual optical structure or source prescription require the user's confirmation.
2. Use the pinned interpreter in `references/runtime-lock.md`. Inputs are read-only local absolute-path JSON files. Choose an absolute output directory that does not exist and whose parent exists; URLs, UNC paths and symlink/reparse path components are rejected.
3. Run `scripts/build.py`. It checks the pinned distributions and imports, validates dimensions and rigid transforms, builds each solid, checks analytic volume/bounds/validity, and only then exports. Every part gets STEP/STL and a STEP geometry roundtrip. Optional assembly gets a named STEP plus separately checked flattened STEP/STL and actual assembly-tree pose readback.
4. Read `report.json`: require PASS, unchanged input, all part geometry/exchange checks true, and assembly pose errors within their stated limits. Exit 1 retains a failure report and any partial files as evidence; a path refusal exits 2 and preserves the existing target. Use PASS reports to identify completed deliverables.
5. Report filenames, units, analytic/measured volumes, bounds, solid/face counts, validity, roundtrip deviations and assembly pose readback source. Treat the output as nominal geometry with no manufacturing or collision qualification.

## Run

Install the pinned environment once from this skill's `requirements.txt` (see `references/runtime-lock.md`). `<python>` is that environment's interpreter and `<skill-dir>` is this skill's folder. Paths are absolute; the output directory must not exist yet, and an existing one, even empty, is refused.

```bash
<python> -X utf8 -I <skill-dir>/scripts/build.py --input <skill-dir>/examples/input.json --output-dir /absolute/new-output-dir
```

The bundled `examples/input.json` builds both part types and a two-part assembly. For user data replace the input argument. `scripts/contract.py --output-dir <absolute/new-directory>` qualifies the environment alone, with the same pinned Python and `-X utf8 -I`. Every build already includes that environment gate; a separate check is unnecessary for a normal build.

## Geometry and pose conventions

- Lengths are mm, volumes mm^3, angles degrees. Both local parts are centered on X/Y with bottom at Z=0 and longitudinal axis +Z. The mount's center aperture and mounting holes go through its full thickness. Tube rings are material attached to the inner wall with explicitly specified axial intervals and clear-aperture radii.
- The 4x4 matrix is an active right-handed local-to-world rigid transformation applied to column vectors `[x,y,z,1]`. Axis-angle form rotates about an axis through the local origin, then translates in world coordinates. Scale, shear and reflection are rejected.
- Pose matrices are read from actual `Assembly.objects[name].loc` and checked against input; transformed solid centroids are checked independently. This is assembly-tree readback. The named assembly STEP's imported hierarchy/poses are not qualified. The separate flattened STEP roundtrip verifies materialized B-rep geometry.
- Geometry requires one valid solid per part, analytic volume relative error <=1e-9 and bounds error <=1e-6 mm. STEP roundtrip requires relative volume error <=1e-8, bounds error <=1e-6 mm, validity and unchanged solid count. Pose rotation entries use 1e-12 absolute tolerance, translations and centroid errors 1e-9 mm.
- STL uses linear tolerance 0.05 mm and angular tolerance 0.1 rad. Its binary triangle count/file length are checked; triangle-mesh volume is not substituted for exact B-rep volume.
- Scope excludes tolerances, threads, fits, collision/clearance checks and automatic poses from optical prescriptions. Lens metrics belong to `design-optical-systems`, optical prescription changes to `ai-zemax-optical-design`. This skill writes only its new output directory and leaves `spectrometer/` and optical prescriptions untouched.

## Regression

Run `tests/regression.py --output-dir <absolute/new-directory>` with the pinned Python and `-X utf8 -I`. It invokes fresh CLI processes and independently checks both analytic volumes/bounds, parameter rebuilds, STEP/STL exchange, matrix/axis-angle poses, moved centroids, illegal dimensions/transforms and overwrite refusal. Read `regression.json` and per-case reports. Its thresholds are fixed in the file. The repository runs it on Linux and Windows through `tests/test_build_optomechanical_parts.py`.
