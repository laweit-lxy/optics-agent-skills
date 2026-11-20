"""Pinned Windows/Linux entry for the radiometric calibration skill."""
import subprocess
import sys

from conftest import REPO, read_report

SKILL = REPO / 'skills' / 'process-radiometric-calibration'


def run(script, *args, isolated=True):
    return subprocess.run([sys.executable, '-X', 'utf8', *(['-I'] if isolated else []),
                           str(SKILL / script), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', timeout=180)


def test_runtime_gate(out_dir):
    for isolated, expected in ((True, 'PASS'), (False, 'FAIL')):
        out = out_dir / expected
        process = run('scripts/contract.py', '--output-dir', out, isolated=isolated)
        assert process.returncode == (0 if isolated else 1), process.stdout + process.stderr
        report = read_report(out / 'environment.json')
        assert report['status'] == expected
        assert report['checks']['isolated_utf8'] == isolated
        assert report['mismatched_distributions'] == {}


def test_existing_output_is_unchanged(out_dir):
    marker = out_dir / 'report.json'
    marker.write_bytes(b'keep me')
    process = run('scripts/process.py', '--input', SKILL / 'examples' / 'input.json', '--output-dir', out_dir)
    assert process.returncode == 2, process.stdout + process.stderr
    assert list(out_dir.iterdir()) == [marker]
    assert marker.read_bytes() == b'keep me'


def test_analytic_and_failure_regressions(out_dir):
    out = out_dir / 'regression'
    process = run('tests/regression.py', '--output-dir', out)
    assert process.returncode == 0, process.stdout + process.stderr
    report = read_report(out / 'regression.json')
    assert report['status'] == 'PASS'
    assert {name: stats['comparison']['status'] for name, stats in report['comparisons'].items()} == {
        'linear': 'AGREE', 'reciprocal': 'DISAGREE',
    }
