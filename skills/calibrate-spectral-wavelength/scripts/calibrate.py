"""Peak-position to wavelength calibration. Native RASCAL units: Angstrom."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
# -I removes script-directory lookup; add only this trusted skill's scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import execute, keys, number, integer, vector, sha


def calibration_atlas(data, limits, medium, conditions):
    import numpy as np
    import importlib.resources
    from rascal.util import load_calibration_lines
    atlas = data['atlas']
    if 'lines' in atlas:
        keys(atlas, ['lines'])
        if not isinstance(atlas['lines'], list) or not atlas['lines']:
            raise ValueError('atlas.lines must be a nonempty list.')
        rows = []
        for i, row in enumerate(atlas['lines']):
            keys(row, ['wavelength_nm'], ['element', 'relative_intensity'])
            w = number(row['wavelength_nm'], 'atlas wavelength_nm', positive=True)
            intensity = number(row.get('relative_intensity', 1), 'relative_intensity', nonnegative=True)
            element = row.get('element', 'custom')
            if not isinstance(element, str) or not element:
                raise ValueError('atlas element must be a nonempty string.')
            rows.append((element, w, intensity))
        source = {'kind': 'custom', 'medium': medium, 'conversion': 'none; custom values already in declared medium'}
    else:
        keys(atlas, ['elements'], ['min_intensity', 'selection'])
        elements = atlas['elements']
        if not isinstance(elements, list) or not elements or any(not isinstance(e, str) or not e for e in elements):
            raise ValueError('atlas.elements must be a nonempty list of element symbols.')
        mi = number(atlas.get('min_intensity', 10), 'min_intensity', nonnegative=True)
        e, w, intensity = load_calibration_lines(elements=elements,
            min_atlas_wavelength=limits[0]*10, max_atlas_wavelength=limits[1]*10,
            min_intensity=mi, min_distance=0., vacuum=medium == 'vacuum', **conditions)
        rows = [(str(a), float(b/10), float(c)) for a, b, c in zip(e, w, intensity)]
        linefile = importlib.resources.files('rascal').joinpath('arc_lines/nist_clean.csv')
        source = {'kind': 'RASCAL bundled NIST', 'sha256': sha(linefile.read_bytes()),
                  'medium': medium, 'min_distance_angstrom': 0.,
                  'conversion': 'native vacuum table retained' if medium == 'vacuum' else 'vacuum to air once by load_calibration_lines'}
    rows = [r for r in rows if limits[0] <= r[1] <= limits[1]]
    source['in_band_before_selection'] = len(rows)
    if not rows:
        raise ValueError('No atlas lines in wavelength_range_nm; line table and band do not overlap.')
    # Keep the strongest of close lines; upstream min_distance removes all members.
    if 'selection' in atlas:
        selection = atlas['selection']
        keys(selection, ['bin_width_nm', 'min_separation_nm'])
        width = number(selection['bin_width_nm'], 'bin_width_nm', positive=True)
        sep = number(selection['min_separation_nm'], 'min_separation_nm', nonnegative=True)
        selected = []
        for lo in np.arange(limits[0], limits[1], width):
            candidates = np.array([i for i, row in enumerate(rows) if lo <= row[1] < lo+width], dtype=int)
            for index in candidates[np.argsort([rows[i][2] for i in candidates])[::-1]]:
                row = rows[index]
                if all(abs(row[1] - prev[1]) >= sep and row[1] != prev[1] for prev in selected):
                    selected.append(row)
                    break
        rows = selected
        source['selection'] = selection
    # Wavelength duplicates cannot provide independent matches. Retain strongest.
    unique = {}
    for row in rows:
        if row[1] not in unique or row[2] > unique[row[1]][2]:
            unique[row[1]] = row
    source['duplicate_wavelengths_removed'] = len(rows)-len(unique)
    return sorted(unique.values(), key=lambda r: r[1]), source


def calibrate(data, out):
    import numpy as np
    from rascal.atlas import Atlas
    from rascal.calibrator import Calibrator
    keys(data, ['peaks_pixel', 'num_pixels', 'atlas', 'wavelength_range_nm', 'wavelength_medium',
                'polynomial_degree', 'seed', 'max_chord_deviation_nm'],
         ['peak_sigma_pixel', 'holdout_lines', 'air_conditions'])
    n = integer(data['num_pixels'], 'num_pixels', 2, 10000000)
    degree = integer(data['polynomial_degree'], 'polynomial_degree', 1, 5)
    seed = integer(data['seed'], 'seed', 0, 2**32-1)
    limits = vector(data['wavelength_range_nm'], 'wavelength_range_nm', 2)
    if not 0 < limits[0] < limits[1]:
        raise ValueError('wavelength_range_nm must be positive and increasing.')
    medium = data['wavelength_medium']
    if medium not in ('air', 'vacuum'):
        raise ValueError('wavelength_medium must be air or vacuum.')
    conditions = {'temperature': 273.15, 'pressure': 101325., 'relative_humidity': 0.}
    if 'air_conditions' in data:
        keys(data['air_conditions'], ['temperature_K', 'pressure_Pa', 'relative_humidity_percent'])
        conditions = {
            'temperature': number(data['air_conditions']['temperature_K'], 'temperature_K', positive=True),
            'pressure': number(data['air_conditions']['pressure_Pa'], 'pressure_Pa', positive=True),
            'relative_humidity': number(data['air_conditions']['relative_humidity_percent'], 'relative_humidity_percent', nonnegative=True)}
        if conditions['relative_humidity'] > 100:
            raise ValueError('relative_humidity_percent must be <=100.')
    peaks = data['peaks_pixel']
    if not isinstance(peaks, list) or not peaks:
        raise ValueError('peaks_pixel must be a nonempty list.')
    peaks = np.array([number(p, 'peak pixel') for p in peaks])
    if np.any(peaks < 0) or np.any(peaks > n-1) or len(np.unique(peaks)) != len(peaks):
        raise ValueError('Peak positions must be distinct and within [0, num_pixels-1].')
    sigma = data.get('peak_sigma_pixel')
    if sigma is not None:
        if not isinstance(sigma, list) or len(sigma) != len(peaks):
            raise ValueError('peak_sigma_pixel must have one value per peak.')
        sigma = [number(s, 'peak_sigma_pixel', positive=True) for s in sigma]
    holdout = data.get('holdout_lines', [])
    if not isinstance(holdout, list):
        raise ValueError('holdout_lines must be a list.')
    hold = []
    for row in holdout:
        keys(row, ['pixel', 'wavelength_nm'], ['sigma_pixel'])
        p = number(row['pixel'], 'holdout pixel')
        w = number(row['wavelength_nm'], 'holdout wavelength_nm', positive=True)
        if not 0 <= p <= n-1 or not limits[0] <= w <= limits[1]:
            raise ValueError('Holdout pixel/wavelength outside detector/band.')
        item = {'pixel': p, 'wavelength_nm': w}
        if 'sigma_pixel' in row:
            item['sigma_pixel'] = number(row['sigma_pixel'], 'holdout sigma_pixel', positive=True)
        hold.append(item)
    if len({h['pixel'] for h in hold}) != len(hold) or len({h['wavelength_nm'] for h in hold}) != len(hold):
        raise ValueError('Holdout pixels and wavelengths must be distinct.')
    excluded = {i for i, p in enumerate(peaks) if any(abs(p-h['pixel']) <= 1e-8 for h in hold)}
    order = sorted((i for i in range(len(peaks)) if i not in excluded), key=lambda i: peaks[i])
    required = max(10, degree+3)
    if len(order) < required:
        raise ValueError(f'Too few training peaks: {len(order)}; require at least {required} after holdout exclusion.')
    rows, source = calibration_atlas(data, limits, medium, conditions)
    original_count = len(rows)
    rows = [r for r in rows if all(abs(r[1]-h['wavelength_nm']) > 1e-7 for h in hold)]
    if len(rows) < required:
        raise ValueError(f'Too few in-band atlas lines after selection/holdout: {len(rows)}; require {required}.')
    deviation = number(data['max_chord_deviation_nm'], 'max_chord_deviation_nm', nonnegative=True)
    candidate_nm = max(0.10, 1.25*deviation)
    linearity_nm = max(3., 1.5*deviation)
    training = peaks[order]
    # These constructor warnings precede the explicit axis correction and are retained in stderr.
    c = Calibrator(peaks=training)
    c.set_calibrator_properties(num_pix=n, pixel_list=np.arange(n), seed=seed, log_level='warning')
    if len(c.pixel_list) != n or not np.array_equal(c.pixel_list, np.arange(n)):
        raise RuntimeError('RASCAL detector axis was not correctly set.')
    c.set_hough_properties(num_slopes=1000, xbins=100, ybins=100,
                          min_wavelength=limits[0]*10, max_wavelength=limits[1]*10,
                          range_tolerance=100., linearity_tolerance=linearity_nm*10)
    c.set_ransac_properties(sample_size=max(5, degree+1), top_n_candidate=8, linear=True, filter_close=True,
                            ransac_tolerance=1., minimum_matches=required, minimum_peak_utilisation=.6,
                            minimum_fit_error=1e-6)
    atlas = Atlas()
    # Values already have the requested medium; vacuum=True here would convert again.
    atlas.add_user_atlas(elements=[r[0] for r in rows], wavelengths=[r[1]*10 for r in rows],
                         intensities=[r[2] for r in rows], vacuum=False)
    c.set_atlas(atlas, candidate_tolerance=candidate_nm*10, constrain_poly=True)
    c.do_hough_transform()
    native, pixels, waves, library_rms, residual, peak_util, atlas_util = c.fit(
        max_tries=2000, fit_deg=degree, fit_type='poly', fit_tolerance=1.,
        candidate_tolerance=candidate_nm*10, progress=False)
    coeff = np.asarray(native)/10
    pixels = np.asarray(pixels)
    waves = np.asarray(waves)/10
    if coeff.shape != (degree+1,) or not np.all(np.isfinite(coeff)) or len(pixels) == 0:
        raise RuntimeError('RASCAL returned no finite polynomial/matches.')
    pairs = {}
    seen_waves = set()
    for p, w in zip(pixels, waves):
        nearest = int(np.argmin(abs(training-p)))
        index = order[nearest]
        if abs(peaks[index]-p) > 1e-8 or index in pairs or float(w) in seen_waves:
            raise RuntimeError('RASCAL returned duplicate/ambiguous peak-line identities; no usable coefficients.')
        if min(abs(w-r[1]) for r in rows) > 1e-7:
            raise RuntimeError('RASCAL matched an unavailable atlas line.')
        pairs[index] = float(w)
        seen_waves.add(float(w))
    residual_nm = np.array([float(np.polynomial.polynomial.polyval(peaks[i], coeff)-w) for i, w in pairs.items()])
    fit_rms = float(np.sqrt(np.mean(residual_nm**2)))
    derivative = np.polynomial.polynomial.polyder(coeff)
    critical = np.polynomial.polynomial.polyroots(np.polynomial.polynomial.polyder(derivative)) if degree > 1 else []
    probe = [0., float(n-1)] + [float(x.real) for x in critical if abs(x.imag) < 1e-10 and 0 < x.real < n-1]
    slopes = np.polynomial.polynomial.polyval(probe, derivative)
    endpoints = np.polynomial.polynomial.polyval([0., float(n-1)], coeff)
    checks = {'finite_fit': bool(np.isfinite(fit_rms) and np.isfinite(library_rms)),
              'minimum_matches': len(pairs) >= required,
              'peak_utilisation': len(pairs)/len(training) >= .6,
              'fit_rms_le_0_10_nm': fit_rms <= .10,
              'increasing_on_full_axis': bool(np.all(slopes > 0)),
              'endpoints_within_10_nm_of_requested_range': bool(np.all(abs(endpoints-limits) <= 10.))}
    matched = []
    for i, p in enumerate(peaks):
        row = {'input_index': i, 'pixel': float(p)}
        if i in excluded:
            row.update(status='EXCLUDED_HOLDOUT', reason='pixel reserved for independent evaluation')
        elif i in pairs:
            row.update(status='MATCHED', wavelength_nm=pairs[i], residual_nm=float(np.polynomial.polynomial.polyval(p, coeff)-pairs[i]))
        else:
            row.update(status='REJECTED', reason='no accepted RANSAC atlas assignment; physical cause not inferred')
        if sigma is not None:
            row.update(sigma_pixel=sigma[i], local_sigma_wavelength_nm=float(abs(np.polynomial.polynomial.polyval(p, derivative))*sigma[i]))
        matched.append(row)
    for h in hold:
        h['predicted_nm'] = float(np.polynomial.polynomial.polyval(h['pixel'], coeff))
        h['error_nm'] = h['predicted_nm']-h['wavelength_nm']
    errors = np.array([h['error_nm'] for h in hold])
    hold_rms = float(np.sqrt(np.mean(errors**2))) if hold else None
    hold_max = float(np.max(abs(errors))) if hold else None
    if hold:
        checks['holdout_rms_le_0_10_nm'] = hold_rms <= .10
        checks['holdout_max_le_0_20_nm'] = hold_max <= .20
    passed = all(checks.values())
    return {'status': 'PASS' if passed else 'FAIL',
        'polynomial': {'basis': 'power', 'order': 'ascending: constant first', 'pixel_origin': 0,
                       'domain_pixel': [0, n-1], 'wavelength_medium': medium,
                       'coefficients': [{'power': k, 'value': float(v), 'unit': 'nm' if k == 0 else f'nm/pixel^{k}'} for k, v in enumerate(coeff)]} if passed else None,
        'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v],
        'error': None if passed else {'type': 'AcceptanceFailure', 'message': 'Fit/holdout acceptance failed; coefficients withheld.'},
        'fit_residual_rms_nm': fit_rms, 'library_fit_rms_nm': float(library_rms/10),
        'peaks': matched, 'peak_utilisation': len(pairs)/len(training), 'atlas_utilisation': len(pairs)/len(rows),
        'holdout': {'count': len(hold), 'lines': hold, 'rms_nm': hold_rms, 'max_abs_error_nm': hold_max,
                    'removed_atlas_rows': original_count-len(rows), 'removed_input_peaks': len(excluded)},
        'atlas': {'source': source, 'used_lines': [{'element': r[0], 'wavelength_nm': r[1], 'relative_intensity': r[2]} for r in rows]},
        'settings': {'seed': seed, 'degree': degree, 'num_pixels': n, 'pixel_list': 'explicit np.arange(num_pixels)',
                     'wavelength_medium': medium, 'air_conditions_native': conditions,
                     'candidate_tolerance_nm': candidate_nm, 'declared_max_chord_deviation_nm': deviation,
                     'linearity_tolerance_nm': linearity_nm, 'range_tolerance_nm': 10., 'fit_tolerance_nm': .10,
                     'num_slopes': 1000, 'xbins': 100, 'ybins': 100, 'top_n_candidate': 8,
                     'minimum_matches': required, 'sample_size': max(5, degree+1), 'max_tries': 2000},
        'limitations': ['Increasing dispersion only; quadratic synthetic regression qualified.',
                        'Peak sigmas are retained and converted by local derivative; RANSAC is unweighted by measurement sigma. No coefficient covariance.',
                        'A successful fit without holdout has no independent accuracy check; wrong physical identities need external truth.',
                        'RASCAL 0.3.11 unique-candidate aggregation issue remains upstream; ambiguous returned matches fail.',
                        'No peak finding, 2D extraction, plotting, or measured instrument qualification.']}


if __name__ == '__main__':
    sys.exit(execute(calibrate))
