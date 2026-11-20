# Methods and sources

## Band average and reflectance

Use `X_band = ∫ X(λ) R(λ) dλ / ∫ R(λ) dλ` for both radiance and a supplied extraterrestrial solar spectrum. After converting to µm and to spectral density per µm, the code places the knots of both piecewise-linear interpolants on the same grid. On each segment of width `h`, the product integral is `h × ((2R₀+R₁)X₀ + (R₀+2R₁)X₁)/6`, exact for the interpolants. The reported SRF area is the integral of the original relative response over µm. Multiplying the relative response by a positive constant does not change the band average. This method does not infer unresolved spectral structure or convert photon response to energy response; use an SRF appropriate to the input spectrum and instrument definition.

`ρ = π · L_band · d² / (E_band · cos(θs))` is dimensionless; `E_band` is referenced to 1 au. Use the reflectance calculation for solar-reflective bands where emitted thermal radiance is negligible. The seasonal distance approximation uses [FAO Irrigation and Drainage Paper 56, Eq. 23](https://www.fao.org/4/x0490e/x0490e07.htm): `d = [1 + 0.033 cos(2π DOY/365)]^(-1/2)` in au. DOY is one-based in the given calendar year (Feb 29 is day 60); the approximation's denominator remains 365. This is a daily approximation rather than an orbital ephemeris. The tool does not calculate atmospheric or surface reflectance, perform DN calibration, or replace the official [USGS Landsat Collection Level-1 reflectance coefficients](https://www.usgs.gov/landsat-missions/using-usgs-landsat-level-1-data-product).

## Uncertainty and agreement

Following [JCGM 100:2008](https://www.bipm.org/en/committees/jc/jcgm/publications) for first-order propagation with independent inputs, compute `u_GUM = sqrt(sum((c_i u_i)^2))`, where `c_i` is the partial derivative of `ρ` in canonical units. For angle in degrees the derivative includes `π/180`. Each budget row gives the sensitivity and the magnitude of its standard uncertainty contribution. The standard uncertainties and distribution parameters are treated as known; no finite-degrees-of-freedom calculation is performed.

Monte Carlo (MC) samples the specified independent PDFs with NumPy PCG64 and evaluates the same forward model. It reports the mean, sample standard deviation (N−1 divisor), and empirical equal-tail 95% interval. Agreement requires both:

- `abs(mean_MC − ρ_nominal) ≤ 0.10 × max(u_GUM, u_MC)`;
- `abs(u_MC − u_GUM) ≤ 0.05 × max(u_GUM, u_MC)`.

Each threshold has a numerical floor of `32 × ε_float64 × max(abs(ρ_nominal), abs(mean_MC))` to avoid comparing roundoff to zero. Report `AGREE` only if both pass. These thresholds are numerical screening criteria, not an interval equivalence test or the adaptive validation in [JCGM 101:2008](https://www.bipm.org/en/committees/jc/jcgm/publications). On `DISAGREE`, examine the magnitude and shape of the input PDFs, near-zero denominators and nonlinear behavior; repeat MC with a larger sample and another seed to check stability before choosing a result. No GUM coverage probability is implied by a standard uncertainty.

The budget starts with the convolved band quantities. It does not estimate uncertainties from spectral samples, wavelength registration or SRF shape, and does not model input correlations. Obtain band-level uncertainties separately; when shared calibration induces correlation, an independent-input budget is not appropriate. To keep the domain of the ratio defined, use bounded PDFs for irradiance, distance and zenith. Normal radiance draws represent measurement noise and can be negative.

Methodology reference for the uncertainty workflow: Timothy Kassis, Vinayak Agarwal, Yuhuan He, Darshil Patel, and Aubrey M. Brueckner (2026), *Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*. [arXiv:2609.00065](https://doi.org/10.48550/arXiv.2609.00065).

## Data provenance and redistribution

The bundled SRF, radiance and solar CSVs and the regression fixtures are synthetic, authored for this repository, and covered by its [MIT license](../../../LICENSE). No mission table or third-party spectrum is redistributed. For local inputs, see the [USGS Spectral Characteristics Viewer](https://landsat.usgs.gov/spectral-characteristics-viewer) (Landsat tables under Sensor RSRs) and [Copernicus SentiWiki S2 Documents](https://sentiwiki.copernicus.eu/web/s2-documents) (Sentinel-2 Spectral Response Functions). These links are format references, not blanket licenses for the files they link. Check the specific data file's provenance and terms before redistributing it, and record the material's sensor, band, revision and source when using it.
