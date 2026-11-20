"""Local read-only inputs, exclusive output and the pinned runtime gate."""
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

SKILL = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 16 * 1024**2


def local_path(text, *, base=None):
    if not isinstance(text, str) or not text or '://' in text or text.startswith(('\\\\', '//')):
        raise ValueError('Use a local file path, not a URL or UNC path.')
    p = Path(text)
    if not p.is_absolute():
        if base is None or p.anchor or '..' in p.parts:
            raise ValueError('Use an absolute path or a CSV path relative to its JSON directory without traversal.')
        p = base / p
    if '..' in p.parts or any(':' in part for part in p.parts[1:]):
        raise ValueError('Parent traversal and alternate streams are not accepted in paths.')
    for part in [*reversed(p.parents), p]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f'Symlink/reparse path rejected: {part}')
    return p


def new_output(text):
    path = local_path(text)
    if not path.parent.is_dir():
        raise ValueError('Output parent must exist.')
    path.mkdir()  # Atomically refuse any existing file or directory.
    return path


def file_data(path, suffix):
    if path.suffix.lower() != suffix or not path.is_file():
        raise ValueError(f'Expected a regular local {suffix} file: {path}')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f'File exceeds the {MAX_FILE_BYTES}-byte limit: {path}')
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Inputs:
    def __init__(self):
        self.records = {}

    def read(self, role, path, suffix):
        raw = file_data(path, suffix)
        self.records[role] = {'path': str(path), 'sha256_before': sha(raw)}
        return raw.decode('utf-8-sig')

    def verify(self):
        for record in self.records.values():
            try:
                path = local_path(record['path'])
                record['sha256_after'] = sha(file_data(path, path.suffix.lower()))
                record['unchanged'] = record['sha256_before'] == record['sha256_after']
            except (OSError, ValueError) as exc:
                record['unchanged'] = False
                record['verification_error'] = str(exc)
        return all(record['unchanged'] for record in self.records.values())


def strict_json(text):
    def reject_constant(value):
        raise ValueError(f'Nonfinite JSON token: {value}')

    def unique_fields(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f'Duplicate JSON field: {key}')
            obj[key] = value
        return obj

    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_fields)


def keys(obj, required, optional=()):
    if not isinstance(obj, dict):
        raise ValueError('Expected a JSON object.')
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f'Invalid fields; missing={sorted(missing)}, unknown={sorted(extra)}.')


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    return float(value)


def runtime_check():
    requirements = (SKILL / 'requirements.txt').read_bytes()
    modules = json.loads((SKILL / 'references/runtime.json').read_text(encoding='utf-8'))['imports']
    expected = dict(line.split('==') for line in requirements.decode('utf-8').splitlines() if line)
    actual = {re.sub(r'[-_.]+', '-', d.metadata['Name']).lower(): d.version
              for d in importlib.metadata.distributions()}
    mismatches = {k: {'pinned': v, 'installed': actual.get(k)} for k, v in expected.items() if actual.get(k) != v}
    checks = {'isolated_utf8': bool(sys.flags.isolated and sys.flags.utf8_mode),
              'python_3_12_64bit': sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32,
              'locked_distributions': not mismatches}
    report = {'checks': checks, 'python': sys.version, 'executable': sys.executable,
              'requirements_sha256': sha(requirements), 'engine_imports': modules,
              'installed_versions': actual, 'mismatched_distributions': mismatches,
              'unpinned_distributions': sorted(actual.keys() - expected.keys())}
    checks['imports'] = False
    if all(ok for name, ok in checks.items() if name != 'imports'):
        try:
            for name in modules:
                importlib.import_module(name)
            checks['imports'] = True
        except Exception as exc:
            report['import_error'] = f'{type(exc).__name__}: {exc}'
    report['status'] = 'PASS' if all(checks.values()) else 'FAIL'
    return report


def dump(path, data):
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text + '\n')


def main(worker=None):
    parser = argparse.ArgumentParser(description=worker.__doc__ if worker else 'Check the pinned radiometry runtime.')
    if worker:
        parser.add_argument('--input', required=True, help='Absolute local JSON input; read only.')
    parser.add_argument('--output-dir', required=True, help='Absolute new directory; parent must exist.')
    args = parser.parse_args()
    try:
        out = new_output(args.output_dir)
    except (OSError, ValueError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 2
    runtime = runtime_check()
    name = 'environment.json' if worker is None else 'report.json'
    if worker is None:
        report = runtime
    else:
        inputs = Inputs()
        report = {'schema_version': '1.0', 'status': 'FAIL', 'runtime': runtime,
                  'inputs': inputs.records, 'result': None}
        try:
            if runtime['status'] != 'PASS':
                raise RuntimeError('Pinned runtime gate failed; inspect runtime.checks.')
            path = local_path(args.input)
            data = strict_json(inputs.read('configuration', path, '.json'))
            result = worker(data, path.parent, inputs)
            json.dumps(result, allow_nan=False)
            report.update(status='PASS', result=result)
        except (OSError, ValueError, ArithmeticError, RuntimeError) as exc:
            report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        if not inputs.verify():
            report.update(status='FAIL', result=None)
            report['input_verification_error'] = 'An input changed or could not be re-read.'
    dump(out / name, report)
    print(json.dumps({'status': report['status'], 'report': str(out / name), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
