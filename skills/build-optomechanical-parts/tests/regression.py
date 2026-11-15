"""Analytic CAD acceptance through fresh CLI processes, no engine in test runner."""
from pathlib import Path
import copy
import json
import math
import struct
import subprocess
import sys
SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from contract import new_output, dump, sha


def run_case(root, name, data):
    src = root / f'{name}.json'
    dump(src, data)
    before = sha(src.read_bytes())
    command = [sys.executable, '-X', 'utf8', '-I', str(SKILL / 'scripts/build.py'), '--input', str(src), '--output-dir', str(root / name)]
    process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180)
    (root / f'{name}.stdout.log').write_text(process.stdout, encoding='utf-8')
    (root / f'{name}.stderr.log').write_text(process.stderr, encoding='utf-8')
    result = json.loads((root / name / 'report.json').read_text(encoding='utf-8'))
    return process.returncode, result, before == sha(src.read_bytes()) == result['input']['sha256_after'], command


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    out = new_output(args.output_dir)
    data = json.loads((SKILL / 'examples/input.json').read_text(encoding='utf-8'))
    code, report, same, command = run_case(out, 'baseline', data)
    checks = {'baseline_exit_and_source': code == 0 and same and report['status'] == 'PASS'}
    if report['status'] != 'PASS':
        dump(out / 'regression.json', {'status': 'FAIL', 'checks': checks, 'error': report.get('error')})
        print(json.dumps(report.get('error')))
        return 1
    parts = {r['name']: r for r in report['parts']}
    mount, tube = parts['mount']['geometry'], parts['tube']['geometry']
    vm = (60*50-math.pi*12**2-4*math.pi*2**2)*8
    vt = math.pi*(20**2-18**2)*80 + 2*math.pi*(18**2-15**2)*2
    checks['mount_analytic_volume'] = abs(mount['volume_mm3']/vm-1) <= 1e-9
    checks['tube_analytic_volume'] = abs(tube['volume_mm3']/vt-1) <= 1e-9
    for name, geometry, expected in [('mount', mount, [-30,30,-25,25,0,8]), ('tube', tube, [-20,20,-20,20,0,80])]:
        checks[f'{name}_bbox_and_valid'] = geometry['valid'] and geometry['solid_count'] == 1 and max(abs(a-b) for a,b in zip(geometry['bounds_mm'], expected)) <= 1e-6
        exchange = parts[name]['exchange']
        after = exchange['step_readback']
        checks[f'{name}_step_roundtrip'] = (after['valid'] and after['solid_count'] == 1 and abs(after['volume_mm3']/geometry['volume_mm3']-1) <= 1e-8 and max(abs(a-b) for a,b in zip(after['bounds_mm'], geometry['bounds_mm'])) <= 1e-6)
        raw = (out / 'baseline' / exchange['stl']).read_bytes()
        count = struct.unpack('<I', raw[80:84])[0]
        checks[f'{name}_stl'] = count > 0 and len(raw) == 84+50*count
    changed = copy.deepcopy(data)
    changed.pop('assembly')
    changed['parts'][0]['thickness_mm'] = 10
    changed['parts'][1]['length_mm'] = 100
    cc, cr, cs, _ = run_case(out, 'changed', changed)
    checks['changed_exit_and_source'] = cc == 0 and cs and cr['status'] == 'PASS'
    if cr['status'] == 'PASS':
        cm, ct = [r['geometry'] for r in cr['parts']]
        checks['mount_parameter_rebuild'] = abs(cm['volume_mm3']/mount['volume_mm3']-1.25) <= 1e-9 and abs(cm['bounds_mm'][5]-10) <= 1e-6
        expected_delta = math.pi*(20**2-18**2)*20
        checks['tube_parameter_rebuild'] = abs((ct['volume_mm3']-tube['volume_mm3'])/expected_delta-1) <= 1e-9 and abs(ct['bounds_mm'][5]-100) <= 1e-6
    poses = {r['part']: r for r in report['assembly']['poses']}
    angle = math.radians(12)
    c,s = math.cos(angle),math.sin(angle)
    expected = [[c,0,s,3],[0,1,0,-2],[-s,0,c,20],[0,0,0,1]]
    actual = poses['tube']['matrix_local_to_world']
    checks['axis_angle_pose'] = max(abs(actual[i][j]-expected[i][j]) for i in range(4) for j in range(4)) <= 1e-12
    identity = [[1 if i == j else 0 for j in range(4)] for i in range(4)]
    checks['identity_matrix_pose'] = poses['mount']['matrix_local_to_world'] == identity
    # New nontrivial matrix input; independent Rx(30 deg) expectation.
    matrix_data = copy.deepcopy(data)
    c,s = math.cos(math.pi/6),math.sin(math.pi/6)
    matrix = [[1,0,0,7],[0,c,-s,8],[0,s,c,9],[0,0,0,1]]
    matrix_data['assembly']['placements'][0] = {'part':'mount','matrix':matrix}
    mc,mr,ms,_ = run_case(out,'nontrivial-matrix',matrix_data)
    checks['nontrivial_matrix_exit'] = mc == 0 and ms and mr['status'] == 'PASS'
    if mr['status'] == 'PASS':
        pose = next(p for p in mr['assembly']['poses'] if p['part'] == 'mount')
        checks['nontrivial_matrix_pose'] = max(abs(pose['matrix_local_to_world'][i][j]-matrix[i][j]) for i in range(4) for j in range(4)) <= 1e-12
        center = [7,8-4*s,9+4*c] # Original plate center = (0,0,4).
        checks['transformed_solid_centroid'] = max(abs(a-b) for a,b in zip(pose['placed_center_mm'],center)) <= 1e-9
    flat = report['assembly']['flattened_exchange']
    before,after = report['assembly']['geometry'],flat['step_readback']
    checks['assembly_flat_step'] = before['solid_count'] == after['solid_count'] == 2 and after['valid'] and abs(after['volume_mm3']/(vm+vt)-1) <= 1e-8 and max(abs(a-b) for a,b in zip(before['bounds_mm'],after['bounds_mm'])) <= 1e-6
    raw = (out/'baseline'/flat['stl']).read_bytes()
    checks['assembly_stl'] = len(raw) == 84+50*struct.unpack('<I',raw[80:84])[0] and len(raw)>84
    invalid = copy.deepcopy(data)
    invalid['parts'][0]['aperture_radius_mm'] = 40
    reflection = copy.deepcopy(data)
    reflection['assembly']['placements'][0]['matrix'][0][0] = -1
    for name, value, fragment in [('invalid-aperture',invalid,'Central aperture'),('reflection-matrix',reflection,'determinant +1')]:
        fc,fr,fs,_ = run_case(out,name,value)
        checks[name] = fc != 0 and fs and fr['status'] == 'FAIL' and fragment in fr['error']['message']
    # Retrying a used output directory must preserve every already written artifact.
    target = out/'baseline'
    hashes = {str(p.relative_to(target)):sha(p.read_bytes()) for p in target.rglob('*') if p.is_file()}
    retry = subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
    current = {str(p.relative_to(target)):sha(p.read_bytes()) for p in target.rglob('*') if p.is_file()}
    checks['existing_output_refused_unchanged'] = retry.returncode == 2 and 'already exists' in retry.stderr and hashes == current
    summary = {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,
               'analytic_reference_mm3':{'mount':vm,'tube':vt},
               'measured_volume_mm3':{'mount':mount['volume_mm3'],'tube':tube['volume_mm3']},
               'command':command,'criteria':'Thresholds are fixed in this file; no adaptive retries.'}
    dump(out/'regression.json',summary)
    print(json.dumps(summary,indent=2))
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
