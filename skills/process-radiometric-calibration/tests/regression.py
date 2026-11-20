"""Analytic reference cases against the real isolated CLI (no pytest required)."""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / 'scripts'))
from contract import dump, new_output, sha


def run(directory, *args, script='process.py'):
    return subprocess.run([sys.executable, '-X', 'utf8', '-I', str(SKILL / 'scripts' / script),
                           *map(str, args), '--output-dir', str(directory)],
                          capture_output=True, text=True, encoding='utf-8', timeout=90)


def run_case(root, name, data, *, failure=None):
    source = root / f'{name}.json'
    out = root / name
    dump(source, data)
    process = run(out, '--input', source)
    require(process.returncode == (1 if failure else 0), process.stdout + process.stderr)
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    require('configuration' in report['inputs'], f'{name}: input provenance missing')
    for row in report['inputs'].values():
        require(row['unchanged'] and row['sha256_before'] == row['sha256_after'] == sha(Path(row['path']).read_bytes()),
                f'{name}: input hash mismatch')
    if failure:
        require(report['status'] == 'FAIL' and report['result'] is None, f'{name}: result must be withheld')
        require(failure in report['error']['message'], f'{name}: wrong failure {report["error"]}')
    else:
        require(report['status'] == 'PASS', f'{name}: {report.get("error")}')
    return report['result']


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def close(actual, expected, name, *, rel_tol=1e-12):
    require(math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=1e-15), f'{name}: {actual} != {expected}')


def table(root, name, text):
    with (root / name).open('x', encoding='utf-8') as stream:
        stream.write(text)


def regression(root):
    example = SKILL / 'examples'
    data = json.loads((example / 'input.json').read_text(encoding='utf-8'))
    for name in ('srf.csv', 'radiance.csv', 'solar.csv'):
        shutil.copyfile(example / name, root / name)

    # Rectangle + linear L on [0.4,0.6] um: integrals reduce to endpoint averages.
    baseline = run_case(root, 'rectangular-linear', data)
    close(baseline['srf']['raw_area_um'], .08, 'SRF area')
    close(baseline['band_radiance']['value'], 100, 'band radiance')
    toa = baseline['toa']
    close(toa['solar_irradiance_at_1_au']['value'], 1600, 'band irradiance')
    require(toa['solar_irradiance_at_1_au']['source'] == 'srf_convolution', 'wrong irradiance provenance')
    require(toa['day_of_year'] == 365, 'wrong DOY')
    close(toa['earth_sun_distance_au'], 1 / math.sqrt(1.033), 'distance')
    expected_rho = math.pi / (8 * 1.033)  # L/E=1/16, cos(60°)=1/2, d²=1/1.033
    close(toa['reflectance']['value'], expected_rho, 'TOA reflectance')
    linear = toa['uncertainty']
    expected_std = expected_rho * .02  # Only L varies with u(L)=2 and L=100.
    close(linear['gum']['standard_uncertainty'], expected_std, 'linear GUM standard uncertainty')
    mc = linear['monte_carlo']
    require(linear['comparison']['status'] == 'AGREE', 'linear MC should agree with GUM')
    close(mc['standard_uncertainty'], expected_std, 'linear MC standard uncertainty', rel_tol=.02)
    require(abs(mc['mean'] - expected_rho) < .02 * expected_std, 'linear MC mean outside sampling tolerance')
    for got, sign in zip(mc['equal_tail_95_interval'], (-1, 1)):
        require(abs(got - (expected_rho + sign * 1.959964 * expected_std)) < .03 * expected_std,
                'linear MC interval outside sampling tolerance')

    direct = copy.deepcopy(data)
    del direct['toa']['solar_spectrum']
    direct['toa']['band_solar_irradiance'] = {'value': 1.6, 'value_unit': 'W/m^2/nm'}
    toa_direct = run_case(root, 'direct-irradiance', direct)['toa']
    require(toa_direct['solar_irradiance_at_1_au']['source'] == 'direct_input', 'wrong direct provenance')
    close(toa_direct['reflectance']['value'], expected_rho, 'direct/convolved irradiance agreement')
    require(toa_direct['uncertainty']['monte_carlo'] == mc, 'same-seed Monte Carlo replay mismatch')

    joint = copy.deepcopy(direct)
    joint['toa']['acquisition_date'] = '2024-02-29'
    joint['toa']['uncertainty']['inputs'].update(
        band_solar_irradiance={'standard_uncertainty': 8, 'distribution': 'rectangular'},
        earth_sun_distance_au={'standard_uncertainty': .001, 'distribution': 'rectangular'},
        solar_zenith_deg={'standard_uncertainty': .5, 'distribution': 'rectangular'},
    )
    toa_joint = run_case(root, 'four-inputs-leap-day', joint)['toa']
    require(toa_joint['day_of_year'] == 60, 'leap-day DOY')
    distance = (1 + .033 * math.cos(120 * math.pi / 365))**-.5
    rho = math.pi * distance**2 / 8
    close(toa_joint['reflectance']['value'], rho, 'leap-day TOA')
    u_rel = math.sqrt(.02**2 + .005**2 + (.002 / distance)**2 + (math.sqrt(3) * math.pi / 360)**2)
    close(toa_joint['uncertainty']['gum']['standard_uncertainty'], rho * u_rel, 'four-input GUM')
    require(toa_joint['uncertainty']['comparison']['status'] == 'AGREE', 'small joint uncertainties should agree')

    # R=t and L=3t normalized to t=(lambda-0.4)/0.2. The mean is 3*(1/3)/(1/2)=2.
    srf_only = copy.deepcopy(data)
    del srf_only['toa']
    table(root, 'ramp.csv', '﻿wavelength,response\n0.4,0\n0.6,50\n')
    table(root, 'linear.csv', 'wavelength,value\n400,0\n600,3\n')
    product = copy.deepcopy(srf_only)
    product['srf'].update(csv='ramp.csv', wavelength_unit='um')
    product['radiance'].update(csv='linear.csv', wavelength_unit='nm', value_unit='W/m^2/sr/um')
    weighted = run_case(root, 'linear-product', product)
    close(weighted['band_radiance']['value'], 2, 'exact quadratic product integral')
    require(weighted['toa'] is None, 'unexpected TOA result in SRF-only mode')
    table(root, 'ramp-scaled.csv', 'wavelength,response\n0.4,0\n0.6,5\n')
    product['srf']['csv'] = 'ramp-scaled.csv'
    close(run_case(root, 'scaled-response', product)['band_radiance']['value'], 2, 'SRF scale invariance')

    # A spectrum kink not in the SRF knots must be included. Triangle area is 0.2.
    table(root, 'kink.csv', 'wavelength,value\n0.4,0\n0.45,2\n0.6,0\n')
    srf_only['radiance'].update(csv='kink.csv', value_unit='W/m^2/sr/um')
    close(run_case(root, 'merged-knots', srf_only)['band_radiance']['value'], 1, 'spectrum knot included')
    table(root, 'padded.csv', 'wavelength,response\n350,0\n400,0\n500,1\n600,0\n650,0\n')
    srf_only['srf']['csv'] = 'padded.csv'
    padded = run_case(root, 'zero-padding', srf_only)
    require(padded['srf']['support_um'] == [.4, .6], 'zero padding is not support')
    table(root, 'short.csv', 'wavelength,value\n0.401,0\n0.6,2\n')
    srf_only['radiance']['csv'] = 'short.csv'
    run_case(root, 'missing-shoulder', srf_only, failure='does not cover SRF support')
    invalid = copy.deepcopy(data)
    invalid['toa']['solar_spectrum'].update(csv='short.csv', wavelength_unit='um', columns=['wavelength', 'value'])
    run_case(root, 'short-solar-spectrum', invalid, failure='solar_spectrum range')
    invalid['srf']['csv'] = '../srf.csv'
    run_case(root, 'parent-traversal', invalid, failure='without traversal')
    invalid = copy.deepcopy(data)
    invalid['toa']['band_solar_irradiance'] = direct['toa']['band_solar_irradiance']
    run_case(root, 'ambiguous-solar-source', invalid, failure='requires exactly one')
    invalid = copy.deepcopy(direct)
    invalid['toa']['band_solar_irradiance']['value'] = 0
    run_case(root, 'zero-irradiance', invalid, failure='must be positive and finite')
    table(root, 'zero.csv', 'wavelength,response\n400,0\n600,0\n')
    invalid = copy.deepcopy(data)
    invalid['srf']['csv'] = 'zero.csv'
    run_case(root, 'zero-srf', invalid, failure='positive area')
    table(root, 'duplicate.csv', 'wavelength,response\n400,1\n400,1\n')
    invalid['srf']['csv'] = 'duplicate.csv'
    run_case(root, 'duplicate-wavelength', invalid, failure='strictly increasing')
    invalid = copy.deepcopy(data)
    invalid['radiance']['value_unit'] = 'W/m^2/sr'
    run_case(root, 'missing-density-unit', invalid, failure='Unsupported value_unit')

    # A uniform error in irradiance on [100,3100] W/m^2/um makes 1/E sharply nonlinear.
    nonlinear = copy.deepcopy(direct)
    nonlinear['toa']['uncertainty']['inputs'] = {
        'band_solar_irradiance': {'standard_uncertainty': 1500 / math.sqrt(3), 'distribution': 'rectangular'},
    }
    divergent = run_case(root, 'reciprocal-nonlinearity', nonlinear)['toa']['uncertainty']
    require(divergent['comparison']['status'] == 'DISAGREE' and divergent['warnings'], 'nonlinearity not flagged')
    factor = expected_rho * 1600
    exact_mean = factor * math.log(3100 / 100) / 3000
    exact_std = factor * math.sqrt(1 / (100 * 3100) - (math.log(31) / 3000)**2)
    close(divergent['monte_carlo']['mean'], exact_mean, 'reciprocal MC mean', rel_tol=.02)
    close(divergent['monte_carlo']['standard_uncertainty'], exact_std, 'reciprocal MC standard uncertainty', rel_tol=.03)
    nonlinear['toa']['uncertainty']['inputs']['band_solar_irradiance']['standard_uncertainty'] = 1000
    run_case(root, 'out-of-domain-irradiance-pdf', nonlinear, failure='support must be strictly positive')
    nonlinear['toa']['uncertainty']['inputs'] = {
        'solar_zenith_deg': {'standard_uncertainty': 20, 'distribution': 'rectangular'},
    }
    run_case(root, 'out-of-domain-zenith-pdf', nonlinear, failure='support must lie in [0, 90)')

    return {'status': 'PASS', 'band_radiance': baseline['band_radiance'],
            'band_irradiance': toa['solar_irradiance_at_1_au'], 'reflectance': toa['reflectance'],
            'comparisons': {key: {k: row[k] for k in ('gum', 'monte_carlo', 'comparison')}
                            for key, row in (('linear', linear), ('reciprocal', divergent))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    out = new_output(parser.parse_args().output_dir)
    try:
        summary = regression(out)
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        summary = {'status': 'FAIL', 'error': str(exc)}
    dump(out / 'regression.json', summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
