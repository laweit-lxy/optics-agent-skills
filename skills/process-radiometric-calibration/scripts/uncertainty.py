"""Independent band-level input PDFs and a first-order/Monte Carlo comparison."""
import math

import numpy as np

from contract import keys, number

VARIABLES = ('band_radiance', 'band_solar_irradiance', 'earth_sun_distance_au', 'solar_zenith_deg')
UNITS = ('W/m^2/sr/um', 'W/m^2/um', 'au', 'deg')


def reflectance(radiance, irradiance, distance, zenith_deg):
    # This numeric model is used for both scalar estimates and MC draws. At this
    # boundary all quantities are already in the canonical units above.
    return np.pi * (radiance / irradiance) * distance**2 / np.cos(np.deg2rad(zenith_deg))


def propagate(spec, estimates):
    keys(spec, ('inputs',), ('samples', 'seed'))
    configs = spec['inputs']
    keys(configs, (), VARIABLES)
    if not configs:
        raise ValueError('uncertainty.inputs must specify at least one input.')
    samples = spec.get('samples', 100_000)
    seed = spec.get('seed', 0)
    for name, value, low, high in (('samples', samples, 10_000, 1_000_000), ('seed', seed, 0, 2**32 - 1)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'uncertainty.{name} must be an integer in [{low}, {high}].')

    radiance, irradiance, distance, zenith_deg = estimates
    nominal = float(reflectance(*estimates))
    sensitivities = (
        float(reflectance(1., irradiance, distance, zenith_deg)),
        -nominal / irradiance,
        2 * nominal / distance,
        nominal * math.tan(math.radians(zenith_deg)) * (math.pi / 180),
    )
    rng = np.random.Generator(np.random.PCG64(seed))
    budget, draws, components = {}, [], []
    for name, unit, center, sensitivity in zip(VARIABLES, UNITS, estimates, sensitivities):
        if name in configs:
            row = configs[name]
            keys(row, ('distribution', 'standard_uncertainty'))
            distribution = row['distribution']
            std = number(row['standard_uncertainty'], f'{name}.standard_uncertainty')
            if std <= 0 or distribution not in ('rectangular', 'normal'):
                raise ValueError(f'{name}: use a positive standard_uncertainty and a supported distribution.')
            if distribution == 'normal' and name != 'band_radiance':
                raise ValueError(f'{name}: use a bounded rectangular PDF to keep all draws in the model domain.')
        else:
            std, distribution = 0., 'fixed'
        half_width = math.sqrt(3) * std if distribution == 'rectangular' else 0.
        if distribution == 'normal':
            draw = rng.normal(center, std, samples)
        elif distribution == 'rectangular':
            lo, hi = center - half_width, center + half_width
            if not math.isfinite(lo) or not math.isfinite(hi):
                raise ValueError(f'{name}: rectangular support must be finite.')
            if name in ('band_solar_irradiance', 'earth_sun_distance_au') and lo <= 0:
                raise ValueError(f'{name}: rectangular support must be strictly positive.')
            # A negative perturbed zenith is not a zenith angle; 90° is singular.
            if name == 'solar_zenith_deg' and not (0 <= lo and hi < 90):
                raise ValueError(f'{name}: rectangular support must lie in [0, 90) degrees.')
            draw = rng.uniform(lo, hi, samples)
        else:
            draw = center
        draws.append(draw)
        components.append(sensitivity * std)
        budget[name] = {'estimate': center, 'unit': unit, 'distribution': distribution,
                        'standard_uncertainty': std, 'sensitivity_per_input_unit': sensitivity,
                        'standard_uncertainty_contribution': abs(components[-1])}

    # GUM law of propagation, independent inputs; compute norm without squaring large coefficients.
    gum_std = math.hypot(*components)
    values = reflectance(*draws)
    if np.all(values == values[0]):
        mc_mean, mc_std = float(values[0]), 0.
    else:
        mc_mean = float(np.mean(values))
        mc_std = float(np.std(values, ddof=1))
    interval = np.quantile(values, [.025, .975]).tolist()
    scale = max(gum_std, mc_std)
    rounding = 32 * np.finfo(np.float64).eps * max(abs(nominal), abs(mc_mean))
    mean_delta = abs(mc_mean - nominal)
    std_delta = abs(mc_std - gum_std)
    mean_limit = float(max(rounding, .10 * scale))
    std_limit = float(max(rounding, .05 * scale))
    agree = mean_delta <= mean_limit and std_delta <= std_limit
    return {
        'gum': {'estimate': nominal, 'standard_uncertainty': gum_std, 'budget': budget},
        'monte_carlo': {'mean': mc_mean, 'standard_uncertainty': mc_std, 'equal_tail_95_interval': interval,
                        'samples': samples, 'seed': seed, 'bit_generator': 'PCG64'},
        'comparison': {'status': 'AGREE' if agree else 'DISAGREE', 'mean_absolute_difference': mean_delta,
                       'mean_limit': mean_limit, 'std_absolute_difference': std_delta, 'std_limit': std_limit},
        'assumptions': ['Specified PDF parameters are treated as known and inputs as independent.',
                        'Variability of spectral shape and SRF, and correlations are not propagated.',
                        'Fixed-sample moment comparison, not a GUM coverage-interval validation.'],
        'warnings': [] if agree else [
            'GUM and Monte Carlo moments disagree: check input PDFs, near-zero denominators and model nonlinearity. '
            'Check Monte Carlo stability with more samples and another seed before choosing a reported uncertainty.'
        ],
    }
