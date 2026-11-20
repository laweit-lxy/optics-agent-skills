"""Convolve one band and optionally compute TOA reflectance and uncertainty."""
import csv
from datetime import date
from io import StringIO
import math
from pathlib import Path
import sys

# Isolated Python omits the script directory. Add only this trusted directory.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import keys, local_path, main, number

WAVELENGTH_SCALE = {'nm': .001, 'um': 1., 'µm': 1.}
RADIANCE_UNIT = 'W/m^2/sr/um'
IRRADIANCE_UNIT = 'W/m^2/um'
MAX_CSV_ROWS = 200_000


def spectral_density_scale(unit, canonical):
    if not isinstance(unit, str) or unit.rpartition('/')[0] != canonical.rpartition('/')[0]:
        raise ValueError(f'Unsupported value_unit; use {canonical} or its per-nm equivalent.')
    per = unit.rpartition('/')[2]
    if per not in WAVELENGTH_SCALE:
        raise ValueError(f'Unsupported value_unit; use {canonical} or its per-nm equivalent.')
    return 1 / WAVELENGTH_SCALE[per]


def read_table(inputs, base, role, spec, value_unit=None):
    import numpy as np

    required = ['csv', 'wavelength_unit']
    if value_unit is not None:
        required.append('value_unit')
    keys(spec, required, ('columns',))
    path = local_path(spec['csv'], base=base)
    wave_unit = spec['wavelength_unit']
    if wave_unit not in ('nm', 'um', 'µm'):
        raise ValueError(f'{role}.wavelength_unit must be nm, um or µm.')
    values_scale = 1. if value_unit is None else spectral_density_scale(spec['value_unit'], value_unit)
    columns = spec.get('columns', ['wavelength', 'response' if value_unit is None else 'value'])
    if (not isinstance(columns, list) or len(columns) != 2 or
            not all(isinstance(c, str) and c and c == c.strip() for c in columns) or columns[0] == columns[1]):
        raise ValueError(f'{role}.columns must name two distinct headers [wavelength, value].')
    table = csv.reader(StringIO(inputs.read(role, path, '.csv'), newline=''), strict=True)
    rows = []
    try:
        header = [c.strip() for c in next(table, ())]
        if len(header) != 2 or set(header) != set(columns):
            raise ValueError(f'{role} CSV must contain exactly these two headers: {columns}.')
        i, j = (header.index(c) for c in columns)
        for row in table:
            if not row:
                continue
            if len(rows) == MAX_CSV_ROWS:
                raise ValueError(f'{role} CSV exceeds {MAX_CSV_ROWS} data rows.')
            if len(row) != 2:
                raise ValueError(f'{role} CSV line {table.line_num} must contain two columns.')
            try:
                rows.append((float(row[i]), float(row[j])))
            except ValueError as exc:
                raise ValueError(f'{role} CSV line {table.line_num} contains a nonnumeric value.') from exc
    except csv.Error as exc:
        raise ValueError(f'{role} CSV line {table.line_num}: {exc}') from exc
    if len(rows) < 2:
        raise ValueError(f'{role} requires at least two samples.')
    wave, values = np.array(rows, dtype=np.float64).T
    if not np.isfinite(wave).all() or not np.isfinite(values).all():
        raise ValueError(f'{role} CSV requires finite numbers.')
    # Division by 1000 (rather than multiplication by .001) keeps common
    # endpoints such as 410 nm and 0.410 um identical in binary64.
    wave = wave / 1000 if wave_unit == 'nm' else wave
    values = values * values_scale
    if wave[0] <= 0 or not np.all(wave[1:] > wave[:-1]):
        raise ValueError(f'{role} wavelengths must be positive and strictly increasing, with no duplicates.')
    if role != 'radiance' and np.any(values < 0):
        raise ValueError(f'{role} values must be nonnegative.')
    return wave, values


class BandResponse:
    """Linear between SRF knots, zero outside; keep shoulders next to nonzero knots."""

    def __init__(self, wave, response):
        import numpy as np

        active = np.flatnonzero(response > 0)
        if not active.size:
            raise ValueError('SRF must have positive area; all responses are zero.')
        selected = slice(max(0, active[0] - 1), active[-1] + 2)
        self.wave = wave[selected]
        self.peak = float(np.max(response))
        self.shape = response[selected] / self.peak
        self.shape_area = float(np.trapezoid(self.shape, self.wave))
        if self.shape_area <= 0 or not math.isfinite(self.shape_area):
            raise ValueError('SRF must have positive finite area.')

    def report(self):
        return {'support_um': [float(self.wave[0]), float(self.wave[-1])],
                'raw_area_um': self.shape_area * self.peak, 'response_peak': self.peak,
                'normalization': 'divide weighted integral by integral of SRF'}

    def mean(self, wave, values, role):
        import numpy as np

        lo, hi = self.wave[0], self.wave[-1]
        if wave[0] > lo or wave[-1] < hi:
            raise ValueError(f'{role} range [{wave[0]}, {wave[-1]}] um does not cover SRF support [{lo}, {hi}] um.')
        interior = wave[(wave > lo) & (wave < hi)]
        knots = np.union1d(self.wave, interior)
        r = np.interp(knots, self.wave, self.shape)
        f = np.interp(knots, wave, values)
        # The product of two linear interpolants is quadratic on each merged
        # segment; integrate it exactly, not by trapezoids on the product.
        r0, r1 = r[:-1], r[1:]
        f0, f1 = f[:-1], f[1:]
        weight = (np.diff(knots) / self.shape_area) / 6
        return float(np.sum((weight * (2*r0 + r1)) * f0 + (weight * (r0 + 2*r1)) * f1))


def solar_distance(text):
    if not isinstance(text, str):
        raise ValueError('acquisition_date must be YYYY-MM-DD.')
    day = date.fromisoformat(text)
    if day.isoformat() != text:
        raise ValueError('acquisition_date must be YYYY-MM-DD.')
    doy = day.timetuple().tm_yday
    # FAO-56 Eq. 23 approximates the inverse-square irradiance factor, not 1/d.
    factor = 1 + .033 * math.cos(math.tau * doy / 365)
    return doy, 1 / math.sqrt(factor)


def toa_result(spec, band_radiance, band, base, inputs):
    from uncertainty import propagate, reflectance

    keys(spec, ('acquisition_date', 'solar_zenith_deg'), ('solar_spectrum', 'band_solar_irradiance', 'uncertainty'))
    spectral = 'solar_spectrum' in spec
    if spectral == ('band_solar_irradiance' in spec):
        raise ValueError('toa requires exactly one of solar_spectrum and band_solar_irradiance.')
    doy, distance = solar_distance(spec['acquisition_date'])
    zenith = number(spec['solar_zenith_deg'], 'solar_zenith_deg')
    if not 0 <= zenith < 90:
        raise ValueError('solar_zenith_deg must be in [0, 90) degrees.')
    if spectral:
        wave, values = read_table(inputs, base, 'solar_spectrum', spec['solar_spectrum'], IRRADIANCE_UNIT)
        irradiance = band.mean(wave, values, 'solar_spectrum')
        source = 'srf_convolution'
    else:
        row = spec['band_solar_irradiance']
        keys(row, ('value', 'value_unit'))
        irradiance = number(row['value'], 'band_solar_irradiance.value') * spectral_density_scale(row['value_unit'], IRRADIANCE_UNIT)
        source = 'direct_input'
    if not math.isfinite(irradiance) or irradiance <= 0:
        raise ValueError('Band solar irradiance at 1 au must be positive and finite.')
    estimates = (band_radiance, irradiance, distance, zenith)
    rho = float(reflectance(*estimates))
    warnings = []
    if not 0 <= rho <= 1:
        warnings.append('TOA reflectance is outside [0, 1]; retained without clipping. Check units, data and geometry.')
    return {'reflectance': {'value': rho, 'unit': '1'}, 'warnings': warnings,
            'solar_irradiance_at_1_au': {'value': irradiance, 'unit': IRRADIANCE_UNIT, 'source': source},
            'acquisition_date': spec['acquisition_date'], 'day_of_year': doy, 'earth_sun_distance_au': distance,
            'earth_sun_distance_method': 'FAO-56 Eq. 23: d=[1+0.033*cos(2*pi*DOY/365)]^(-1/2)',
            'solar_zenith_deg': zenith,
            'uncertainty': propagate(spec['uncertainty'], estimates) if 'uncertainty' in spec else None}


def process(data, base, inputs):
    """Convolve a radiance spectrum with one SRF and optionally calculate TOA reflectance."""
    import numpy as np

    keys(data, ('wavelength_medium', 'srf', 'radiance'), ('toa',))
    if data['wavelength_medium'] not in ('air', 'vacuum'):
        raise ValueError('wavelength_medium must be air or vacuum for all input tables.')
    with np.errstate(over='raise', divide='raise', invalid='raise'):
        band = BandResponse(*read_table(inputs, base, 'srf', data['srf']))
        wave, values = read_table(inputs, base, 'radiance', data['radiance'], RADIANCE_UNIT)
        radiance = band.mean(wave, values, 'radiance')
        return {'wavelength_medium': data['wavelength_medium'], 'srf': band.report(),
                'band_radiance': {'value': radiance, 'unit': RADIANCE_UNIT},
                'toa': toa_result(data['toa'], radiance, band, base, inputs) if 'toa' in data else None}


if __name__ == '__main__':
    sys.exit(main(process))
