"""Local file contract and pinned runtime gate. No engine imported until checked."""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import importlib
import importlib.metadata as md
import json
import math
import os
from pathlib import Path
import platform
import stat
import traceback

SKILL = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def local_path(value, *, exists=True):
    text = str(value)
    if '://' in text or text.startswith(('\\\\', '//')):
        raise ValueError('Use an absolute local path, not URL or UNC.')
    p = Path(text)
    if not p.is_absolute():
        raise ValueError(f'Absolute local path required: {p}')
    for part in [*reversed(p.parents), p]:
        if os.path.lexists(part):
            info = part.lstat()
            if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError(f'Symlink/reparse path rejected: {part}')
    if exists and not p.exists():
        raise ValueError(f'Path does not exist: {p}')
    return p


def new_output(value):
    p = local_path(value, exists=False)
    if os.path.lexists(p):
        raise FileExistsError(f'Output directory already exists; choose a new directory: {p}')
    if not p.parent.is_dir():
        raise ValueError(f'Output parent must exist: {p.parent}')
    p.mkdir()  # Atomic refusal of an existing target.
    return p


def load_input(value):
    p = local_path(value)
    if not p.is_file() or p.suffix.lower() != '.json':
        raise ValueError('Input must be a local regular .json file.')
    raw = p.read_bytes()
    data = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Nonfinite JSON: {x}')))
    if not isinstance(data, dict):
        raise ValueError('Input JSON must be an object.')
    return data, {'path': str(p), 'sha256_before': sha(raw)}


def keys(obj, required, optional=()):
    if not isinstance(obj, dict):
        raise ValueError('Expected JSON object.')
    missing = set(required) - obj.keys()
    unknown = obj.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'Invalid fields; missing={sorted(missing)}, unknown={sorted(unknown)}')


def number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    if positive and value <= 0 or nonnegative and value < 0:
        raise ValueError(f'{name} must be {"positive" if positive else "nonnegative"}.')
    return float(value)


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}].')
    return value


def vector(value, name, length):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f'{name} must have {length} entries.')
    return [number(x, name) for x in value]


def runtime_check():
    lock = json.loads((SKILL / 'references/runtime.json').read_text(encoding='utf-8'))
    checks = {
        'isolated_utf8': bool(sys.flags.isolated and sys.flags.utf8_mode),
        'python_3_12_64bit': sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32,
    }
    normal = lambda x: x.lower().replace('_', '-').replace('.', '-')
    expected = {}
    for line in (SKILL / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        if line.strip():
            name, version = line.strip().split('==')
            expected[normal(name)] = version
    actual = {normal(d.metadata['Name']): d.version for d in md.distributions()}
    # Every pinned distribution must be present at its pinned version. Other
    # distributions (pip, a test runner) are listed, not rejected.
    mismatched = {k: {'pinned': v, 'installed': actual.get(k)} for k, v in expected.items() if actual.get(k) != v}
    checks['locked_distributions'] = not mismatched
    result = {'status': 'FAIL', 'checks': checks, 'python': sys.version, 'platform': platform.platform(),
              'executable': sys.executable, 'installed_versions': actual,
              'mismatched_distributions': mismatched,
              'unpinned_distributions': sorted(set(actual) - set(expected)),
              'requirements_sha256': sha((SKILL / 'requirements.txt').read_bytes()),
              'engine_imports': lock['imports']}
    if all(checks.values()):
        try:
            for module in lock['imports']:
                importlib.import_module(module)
            checks['imports'] = True
        except Exception as exc:
            checks['imports'] = False
            result['import_error'] = f'{type(exc).__name__}: {exc}'
    else:
        checks['imports'] = False
    result['status'] = 'PASS' if all(checks.values()) else 'FAIL'
    return result


def dump(path, data):
    # Strict JSON disallows NaN/Infinity and exclusive mode disallows overwrites.
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def execute(worker):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help='Absolute local JSON input; read-only.')
    parser.add_argument('--output-dir', required=True, help='Absolute directory that must not exist; parent must exist.')
    args = parser.parse_args()
    try:
        out = new_output(args.output_dir)
    except Exception as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 2
    report = {'schema_version': '1.0', 'status': 'FAIL', 'polynomial': None} if worker.__name__ == 'calibrate' else {'schema_version': '1.0', 'status': 'FAIL'}
    try:
        data, report['input'] = load_input(args.input)
        os.environ['MPLBACKEND'] = 'Agg'
        os.environ['MPLCONFIGDIR'] = str(out / 'matplotlib-cache')
        report['runtime'] = runtime_check()
        if report['runtime']['status'] != 'PASS':
            raise RuntimeError('Pinned runtime gate failed; inspect runtime.checks.')
        result = worker(data, out)
        # Validate before merging so serialization failures take the normal FAIL path.
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        report.update(result)
        report['status'] = result.get('status', 'PASS')
    except Exception as exc:
        report['status'] = 'FAIL'
        if 'polynomial' in report:
            report['polynomial'] = None
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        (out / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        if 'input' in report:
            try:
                final = sha(Path(report['input']['path']).read_bytes())
                report['input']['sha256_after'] = final
                report['input']['unchanged'] = final == report['input']['sha256_before']
                if not report['input']['unchanged']:
                    raise RuntimeError('Input changed during execution.')
            except Exception as exc:
                report['status'] = 'FAIL'
                report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
                if 'polynomial' in report:
                    report['polynomial'] = None
    dump(out / 'report.json', report)
    print(json.dumps({'status': report['status'], 'report': str(out / 'report.json'), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pinned environment self-check; imports the engine without GUI.')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        out = new_output(args.output_dir)
        os.environ['MPLBACKEND'] = 'Agg'
        os.environ['MPLCONFIGDIR'] = str(out / 'matplotlib-cache')
        result = runtime_check()
        dump(out / 'environment.json', result)
        print(json.dumps({'status': result['status'], 'report': str(out / 'environment.json')}))
        sys.exit(0 if result['status'] == 'PASS' else 1)
    except Exception as exc:
        print(f'FAIL: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
