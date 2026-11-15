"""Frozen synthetic acceptance; subprocess CLI, independent identities/metrics."""
from pathlib import Path
import copy
import json
import math
import os
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from contract import new_output, dump, sha


def fixture(seed):
    import numpy as np
    from rascal.util import load_calibration_lines
    rng = np.random.default_rng(seed)
    elements, waves_a, intensities = load_calibration_lines(elements=['Hg', 'Ar', 'Ne'],
        min_atlas_wavelength=4000., max_atlas_wavelength=7000., min_intensity=10,
        min_distance=0., vacuum=False, temperature=273.15, pressure=101325., relative_humidity=0.)
    selected = []
    for lo in np.arange(4000., 7000., 100.):
        indices = np.flatnonzero((waves_a >= lo) & (waves_a < lo+100.))
        for index in indices[np.argsort(intensities[indices])[::-1]]:
            if not selected or np.min(abs(waves_a[selected]-waves_a[index])) >= 20.:
                selected.append(int(index))
                break
    selected = np.array(selected, dtype=int)
    selected = selected[np.argsort(waves_a[selected])]
    waves = waves_a[selected]/10
    elements, intensities = elements[selected], intensities[selected]
    true = np.array([400., (300.-4e-6*1300**2)/1300, 4e-6])
    a, b = true[2], true[1]
    true_pixels = 2*(waves-400)/(b+np.sqrt(b*b+4*a*(waves-400)))
    observed = true_pixels+rng.normal(0., .15, len(waves))
    hold = np.arange(len(waves)) % 5 == 2
    fake = []
    while len(fake) < 3:
        x = float(rng.uniform(20., 1280.))
        if min(abs(observed-x)) > 12 and (not fake or min(abs(np.array(fake)-x)) > 12):
            fake.append(x)
    peaks = np.concatenate([observed[~hold], np.array(fake)])
    labels = np.concatenate([np.flatnonzero(~hold), np.full(3, -1)])
    order = np.argsort(peaks)
    peaks, labels = peaks[order], labels[order]
    data = {'peaks_pixel': peaks.tolist(), 'peak_sigma_pixel': [.15]*len(peaks), 'num_pixels': 1301,
            'atlas': {'lines': [{'element': str(e), 'wavelength_nm': float(w), 'relative_intensity': float(i)}
                               for e, w, i in zip(elements, waves, intensities)]},
            'wavelength_range_nm': [400., 700.], 'wavelength_medium': 'air', 'polynomial_degree': 2,
            'seed': seed, 'max_chord_deviation_nm': 2.,
            'air_conditions': {'temperature_K': 273.15, 'pressure_Pa': 101325., 'relative_humidity_percent': 0.},
            'holdout_lines': [{'pixel': float(p), 'wavelength_nm': float(w), 'sigma_pixel': .15}
                              for p, w in zip(observed[hold], waves[hold])]}
    truth = {'labels': labels.tolist(), 'wavelengths_nm': waves.tolist(), 'observed_pixels': observed.tolist(),
             'holdout': hold.tolist(), 'coefficients_nm': true.tolist(), 'fake_pixels': fake}
    return data, truth


def run_case(root, name, data):
    input_path = root / f'{name}.json'
    dump(input_path, data)
    before = sha(input_path.read_bytes())
    output = root / name
    command = [sys.executable, '-X', 'utf8', '-I', str(SKILL / 'scripts/calibrate.py'),
               '--input', str(input_path), '--output-dir', str(output)]
    process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180)
    (root / f'{name}.stdout.log').write_text(process.stdout, encoding='utf-8')
    (root / f'{name}.stderr.log').write_text(process.stderr, encoding='utf-8')
    result = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    unchanged = before == sha(input_path.read_bytes()) == result['input']['sha256_after']
    return process.returncode, result, unchanged, command


def evaluate(result, truth):
    if result['status'] != 'PASS' or result['polynomial'] is None:
        return {'passed': False, 'reason': result.get('error')}
    coeff = [x['value'] for x in result['polynomial']['coefficients']]
    poly = lambda p: sum(c*p**k for k, c in enumerate(coeff))
    errors, wrong, rejected_fake, matched_true = [], 0, 0, 0
    for row in result['peaks']:
        label = truth['labels'][row['input_index']]
        if row['status'] == 'MATCHED':
            wrong += int(label < 0 or abs(row['wavelength_nm']-truth['wavelengths_nm'][label]) > 1e-7)
            if label >= 0:
                matched_true += 1
                errors.append(poly(row['pixel'])-truth['wavelengths_nm'][label])
        elif label < 0:
            rejected_fake += 1
    hold_errors = [poly(p)-w for p, w, h in zip(truth['observed_pixels'], truth['wavelengths_nm'], truth['holdout']) if h]
    train_errors = [poly(p)-w for p, w, h in zip(truth['observed_pixels'], truth['wavelengths_nm'], truth['holdout']) if not h]
    rms = lambda x: math.sqrt(sum(e*e for e in x)/len(x))
    metrics = {'fit_rms_nm': result['fit_residual_rms_nm'], 'training_truth_rms_nm': rms(train_errors),
               'holdout_rms_nm': rms(hold_errors), 'holdout_max_abs_nm': max(map(abs, hold_errors)),
               'wrong_matches': wrong, 'matched_true': matched_true, 'rejected_fake': rejected_fake,
               'coefficients_nm': coeff}
    metrics['passed'] = (metrics['fit_rms_nm'] <= .10 and metrics['training_truth_rms_nm'] <= .10 and
        metrics['holdout_rms_nm'] <= .10 and metrics['holdout_max_abs_nm'] <= .20 and wrong == 0)
    return metrics


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    out = new_output(args.output_dir)
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['MPLCONFIGDIR'] = str(out / 'fixture-matplotlib-cache')
    checks, runs = {}, []
    for seed in [20261115, 20261116, 20261117, 20261118]:
        data, truth = fixture(seed)
        dump(out / f'truth-{seed}.json', truth)
        code, result, same, command = run_case(out, f'seed-{seed}', data)
        metrics = evaluate(result, truth)
        metrics.update(seed=seed, exit_code=code, input_unchanged=same, command=command)
        runs.append(metrics)
        if seed == 20261115:
            checks['baseline_acceptance'] = code == 0 and same and metrics['passed'] and metrics['matched_true'] == 24 and metrics['rejected_fake'] == 3
            expected = [.03098045, .03364628, .05993431]
            actual = [metrics['training_truth_rms_nm'], metrics['holdout_rms_nm'], metrics['holdout_max_abs_nm']]
            expected_coeff = [400.02284088242104, .22553010718280504, 4.034911019840616e-6]
            checks['matches_reference_to_1e_8'] = all(abs(a-b) <= 1e-8 for a, b in zip(actual, expected)) and all(abs(a-b) <= 1e-8 for a, b in zip(metrics['coefficients_nm'], expected_coeff))
            checks['sigma_retained_not_weighted'] = all(row['sigma_pixel'] == .15 and row['local_sigma_wavelength_nm'] > 0 for row in result['peaks'])
            checks['holdout_atlas_excluded'] = result['holdout']['removed_atlas_rows'] == 6 and result['holdout']['count'] == 6
            # Lamp branch must select the same atlas without truth anchors.
            lamp = copy.deepcopy(data)
            lamp['atlas'] = {'elements': ['Hg', 'Ar', 'Ne'], 'min_intensity': 10,
                              'selection': {'bin_width_nm': 10, 'min_separation_nm': 2}}
            lc, lr, ls, _ = run_case(out, 'lamp-air', lamp)
            lm = evaluate(lr, truth)
            checks['lamp_air_branch'] = lc == 0 and ls and lm['passed'] and all(abs(a['value']-b['value']) < 1e-8 for a, b in zip(lr['polynomial']['coefficients'], result['polynomial']['coefficients']))
    baseline, _ = fixture(20261115)
    few = copy.deepcopy(baseline)
    few['peaks_pixel'], few['peak_sigma_pixel'] = few['peaks_pixel'][:2], [.15, .15]
    band = copy.deepcopy(baseline)
    band['atlas'] = {'lines': [{'wavelength_nm': 800.+i} for i in range(20)]}
    for name, data, text in [('too-few-peaks', few, 'Too few training peaks'), ('out-of-band', band, 'do not overlap')]:
        code, result, same, _ = run_case(out, name, data)
        checks[name] = code != 0 and result['status'] == 'FAIL' and result['polynomial'] is None and text in result['error']['message'] and same
    # Medium preservation is independently exercised with a custom vacuum atlas.
    vacuum = copy.deepcopy(baseline)
    vacuum['wavelength_medium'] = 'vacuum'
    code, result, same, _ = run_case(out, 'custom-vacuum', vacuum)
    checks['custom_vacuum_no_conversion'] = code == 0 and same and result['settings']['wavelength_medium'] == 'vacuum' and result['atlas']['source']['conversion'].startswith('none') and evaluate(result, fixture(20261115)[1])['passed']
    # Include reserved peaks as input: they must be removed before RANSAC.
    isolation = copy.deepcopy(baseline)
    isolation['peaks_pixel'] += [h['pixel'] for h in isolation['holdout_lines']]
    isolation['peak_sigma_pixel'] += [.15]*len(isolation['holdout_lines'])
    code, result, same, _ = run_case(out, 'holdout-peak-isolation', isolation)
    checks['holdout_peaks_excluded'] = code == 0 and same and result['holdout']['removed_input_peaks'] == 6 and sum(r['status'] == 'EXCLUDED_HOLDOUT' for r in result['peaks']) == 6
    summary = {'status': 'PASS' if all(checks.values()) and all(r['passed'] and r['input_unchanged'] and r['exit_code'] == 0 for r in runs) else 'FAIL',
               'checks': checks, 'runs': runs, 'additional_seeds': {'successes': sum(r['passed'] and r['exit_code'] == 0 for r in runs[1:]), 'total': 3},
               'criteria': 'Thresholds are fixed in this file; no adaptive retries.'}
    dump(out / 'regression.json', summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
