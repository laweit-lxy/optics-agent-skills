# Input and output contract

One local absolute-path ordinary JSON file. Unknown fields and nonfinite values fail. Top level requires `units:"mm"` and a nonempty `parts` list; `assembly` is optional. Names start with an ASCII letter and contain only ASCII letters/digits, `_` or `-`; names are unique ignoring case. `assembly`, `assembly-flat` and Windows device names (CON/PRN/AUX/NUL/COM1–9/LPT1–9) are reserved to protect output filenames.

## Rectangular mount

Each part requires:

```json
{
  "name":"mount", "type":"rectangular_mount",
  "width_mm":60, "height_mm":50, "thickness_mm":8,
  "aperture_radius_mm":12, "mounting_hole_radius_mm":2,
  "mounting_hole_centers_mm":[[-23,-18],[-23,18],[23,-18],[23,18]]
}
```

All dimensions/radii positive. Center aperture must fit strictly inside the rectangle. Installation holes share one radius; at least one is required. Each lies strictly inside the plate, disjoint from the center hole and every other installation hole, including their boundaries. XY origin is plate center; Z=0 is its bottom.

Analytic volume: `(width*height - pi*aperture_radius^2 - N*pi*mounting_hole_radius^2)*thickness`.

## Internally baffled tube

```json
{
  "name":"tube", "type":"baffle_tube",
  "outer_radius_mm":20, "inner_radius_mm":18, "length_mm":80,
  "baffles":[
    {"z_mm":20,"thickness_mm":2,"aperture_radius_mm":15},
    {"z_mm":50,"thickness_mm":2,"aperture_radius_mm":15}
  ]
}
```

Radii/length positive, inner radius < outer radius; at least one baffle. Baffle `z_mm` is the local bottom of its ring, not center; z and thickness positive, z+thickness < tube length, aperture radius strictly between zero and inner radius. Axial ring intervals must not overlap; adjacent rings may touch. Tube axis is +Z, centered on X/Y, bottom Z=0. Ring material is fused to the tube wall.

Analytic volume: `pi*(outer_radius^2-inner_radius^2)*length + sum(pi*(inner_radius^2-ring_aperture_radius^2)*ring_thickness)`.

## Assembly

`assembly:{"placements":[ ... ]}` places every named part exactly once. Use one of:

```json
{"part":"mount","matrix":[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}
```

```json
{"part":"tube","translation_mm":[3,-2,20],"axis":[0,1,0],"angle_deg":12}
```

Matrix must be finite 4x4; last row `[0,0,0,1]`, orthonormal upper 3x3 with determinant +1, validation tolerance 1e-12. Translation is in its last column. Axis-angle uses a nonzero finite axis normalized by the script, right-hand positive degrees, rotate about local origin then translate. The resulting Location and actual assembly tree are read back; rotation/translation errors >1e-12/1e-9 mm fail. Nontrivial matrix conversion and transformed centers are tested.

No constraints or collision resolution are applied. Any overlap between placed parts remains in the nominal assembly.

## Outputs

Each part: `<name>.step`, `<name>.stl`. Optional assembly: named `assembly.step` and materialized `assembly-flat.step`, `assembly-flat.stl`. `report.json` records:

- `runtime`: Python/base path, full locked versions, import checks and dependency-list hash;
- `input`: before/after SHA-256 and unchanged status;
- `parts`: original parameters, volume_mm3, bounds_mm ordered `[xmin,xmax,ymin,ymax,zmin,zmax]`, dimensions_mm, center_mm, face_count, solid_count, valid, analytic volume/error, geometry checks, exchange filenames/hashes, STEP readback/errors, binary STL count/length;
- `assembly`: matrices read from the actual tree, expected matrices/errors, moved centroids, materialized geometry and exchange checks. Pose source is the live tree, not STEP imported hierarchy;
- explicit STL settings and scope limits.

Exit 0: PASS. Exit 1: runtime/input/geometry/exchange failure, `status=FAIL`, `error`, `failure.log`; partial geometry files may remain and are not completed deliverables. Exit 2: output-path refusal or CLI usage, stderr only. Existing output directories are always refused; use a fresh directory for retries.
