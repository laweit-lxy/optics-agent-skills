# Classic lens starting points

[Catalog](catalog.json) lists five centered sequential prescriptions. Each entry gives the local ZMX path (relative to the catalog), source and public status, reference EFL and paraxial F-number, field samples, wavelengths, glass treatment, and any adaptations. All lengths are in mm; `length_scale: 1` means the source dimensions were used without rescaling.

| Form | Prescription | Source |
| --- | --- | --- |
| Cooke triplet | [Existing regression ZMX](../tests/data/cooke/cooke-6cd4da4.zmx) | Optiland `CookeTriplet`, commit `6cd4da4`; independent OpticStudio measurements on the ZMX |
| Double-Gauss | [Existing regression ZMX](../tests/data/double-gauss/double-gauss-6cd4da4.zmx) | Optiland `DoubleGauss`, commit `6cd4da4`; independent OpticStudio measurements on the ZMX |
| Tessar | [ZMX](tessar-jp2003005030a.zmx) | [JP2003005030A](https://patents.google.com/patent/JP2003005030A/ja), Example 1, Table 1 |
| Field-flattened Petzval | [ZMX](petzval-comsol.zmx) | [COMSOL 6.4 Petzval Lens](https://doc.comsol.com/6.4/doc/com.comsol.help.models.roptics.petzval_lens/petzval_lens.html), Tables 1–2 |
| Retrofocus wide-angle | [ZMX](retrofocus-us7656591b2.zmx) | [US7656591B2](https://patents.google.com/patent/US7656591B2/en), Example 1, Table 1, infinity configuration ([scan p. 12](https://patentimages.storage.googleapis.com/d6/21/dd/911ef321cb761a/US7656591.pdf#page=12)) |

## Use a starting point

Resolve its `zmx` to an absolute path and pass it to [`design-optical-systems`](../skills/design-optical-systems/SKILL.md) with `--input-zmx`. Use [`cross-check-optical-designs`](../skills/cross-check-optical-designs/SKILL.md) for an independent first-order inspection. Copy the ZMX before adapting it. The two reused prescriptions and their native references stay under [`tests/data`](../tests/data/README.md); the Hubble telescope remains a runtime regression, not a starting-point entry.

These are starting forms. The checks cover the stated first-order convention and import readback, not the source's aberration plots, field illumination, clear apertures, or manufacturability. In the patent examples the tabulated F-number is used to set the nominal entrance pupil diameter (`EFL / FNO`); comparing the computed paraxial F-number tests that input and the imported power, not an independently specified physical aperture. The model glasses reproduce the supplied d-line index and Abbe number without asserting actual glass identity or dispersion away from the d line.

## Reference calculations

For the two regression ZMX files, retain their existing native OpticStudio EFL and ISFN. The catalog's absolute regression windows correspond approximately to relative `1e-4`. The Tessar EFL window is 0.001 mm (the displayed 0.001 mm increment plus prescription rounding); the retrofocus EFL window is 0.05 mm (half its 0.1 mm display increment). The F-number window for both patents is 0.005 (half the displayed increment).

For the paraxial calculation, start a parallel ray at height `y = 1` and reduced angle `u = 0` in air. At each interface use `u ← u − (n_after − n_before)y/R`; in its gap use `y ← y + t u/n_after`. A plane contributes zero power. Immediately after the final refracting surface in air, `EFL = −1/u`; `BFL = −y/u`. This yields the retrofocus image gap in the catalog from the Table 1 d-line indices, because the patent's Bf cell is symbolic.

For the Petzval, use the [SCHOTT Optical Glass Datasheet Collection](https://media.schott.com/api/public/content/820eba3413cc4e788433a3751f8edba9?v=97b3ea2b), PDF pages 13 (N-BK7), 131 (N-KZFS5), 34 (N-SK2), and 99 (N-SF5). Evaluate the Sellmeier equation `n² = 1 + Σ Bᵢλ²/(λ² − Cᵢ)` at 0.55 µm and apply the same ray calculation to COMSOL Table 1. It gives EFL 100.77933919 mm and F/2.42841781 with the Table 2 entrance pupil of 41.5 mm. The stated 100.0 mm is 0.77934 mm below the reconstructed EFL, outside a 0.05 mm rounding window; the computed F-number rounds to the stated approximate F/2.4. Regression uses the calculation, and the catalog retains both published figures. The ZMX leaves the tabulated 1.9548 mm image gap unchanged rather than refocusing to the paraxial BFL. The tabulated 16.631 mm physical stop clear radius and the nominal entrance pupil are different specifications; this ZMX uses the latter for the launch aperture.
