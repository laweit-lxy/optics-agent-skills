# Regression samples

Each folder holds one sequential prescription and an independent OpticStudio reference.

- `<name>-6cd4da4.zmx`: the Cooke triplet, Double-Gauss and Hubble telescope sample models of [Optiland](https://github.com/optiland/optiland) (MIT) at commit `6cd4da40cabc82e395231edd4c0ca75b9a15bd75`, exported to ZMX.
- `<name>-native-reference.json`: EFL, paraxial F-number (ISFN) and working F-number (WFNO) measured in Ansys Zemax OpticStudio 22.2.2 on that ZMX file; `source_sha256` is the ZMX digest. The same values were reproduced in OpticStudio 2024 R1 within `rtol=atol=1e-10`.

Do not regenerate the reference files from Optiland or RayOptics; they exist to check those engines.
