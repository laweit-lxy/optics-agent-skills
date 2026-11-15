"""Headless parameterized CAD in mm; only two explicitly supported part types."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import math
import re
import struct
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import execute, keys, number, vector, sha


def measure(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    # Ignore tessellation caches: STL export changes default BoundingBox on rotated solids.
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = b.Get()
    return {'volume_mm3': shape.Volume(), 'bounds_mm': [xmin, xmax, ymin, ymax, zmin, zmax],
            'dimensions_mm': [xmax-xmin, ymax-ymin, zmax-zmin], 'center_mm': list(shape.Center().toTuple()),
            'face_count': len(shape.Faces()), 'solid_count': len(shape.Solids()), 'valid': shape.isValid()}


def make_part(p):
    import cadquery as cq
    kind = p['type']
    if kind == 'rectangular_mount':
        keys(p, ['name', 'type', 'width_mm', 'height_mm', 'thickness_mm', 'aperture_radius_mm',
                 'mounting_hole_radius_mm', 'mounting_hole_centers_mm'])
        w, h, t, a, r = [number(p[k], k, positive=True) for k in
            ('width_mm', 'height_mm', 'thickness_mm', 'aperture_radius_mm', 'mounting_hole_radius_mm')]
        if 2*a >= min(w, h):
            raise ValueError('Central aperture must fit strictly inside the rectangular plate (2*aperture_radius_mm < min(width_mm,height_mm)).')
        if not isinstance(p['mounting_hole_centers_mm'], list) or not p['mounting_hole_centers_mm']:
            raise ValueError('mounting_hole_centers_mm must be a nonempty list.')
        centers = [vector(x, 'mounting hole center', 2) for x in p['mounting_hole_centers_mm']]
        for i, (x, y) in enumerate(centers):
            if abs(x)+r >= w/2 or abs(y)+r >= h/2:
                raise ValueError(f'Mounting hole {i} must lie strictly inside plate edges.')
            if math.hypot(x, y) <= a+r:
                raise ValueError(f'Mounting hole {i} overlaps/touches central aperture.')
            if any(math.dist((x, y), other) <= 2*r for other in centers[:i]):
                raise ValueError(f'Mounting hole {i} overlaps/touches another mounting hole.')
        part = (cq.Workplane('XY').box(w, h, t, centered=(True, True, False))
                .faces('>Z').workplane().hole(2*a).faces('>Z').workplane().pushPoints(centers).hole(2*r))
        analytic = (w*h-math.pi*a*a-len(centers)*math.pi*r*r)*t
        bounds = [-w/2, w/2, -h/2, h/2, 0., t]
    elif kind == 'baffle_tube':
        keys(p, ['name', 'type', 'outer_radius_mm', 'inner_radius_mm', 'length_mm', 'baffles'])
        ro, ri, length = [number(p[k], k, positive=True) for k in ('outer_radius_mm', 'inner_radius_mm', 'length_mm')]
        if ri >= ro:
            raise ValueError('inner_radius_mm must be less than outer_radius_mm.')
        if not isinstance(p['baffles'], list) or not p['baffles']:
            raise ValueError('baffles must be a nonempty list of internal annular rings.')
        rings = []
        for ring in p['baffles']:
            keys(ring, ['z_mm', 'thickness_mm', 'aperture_radius_mm'])
            z, t, a = [number(ring[k], k, positive=True) for k in ('z_mm', 'thickness_mm', 'aperture_radius_mm')]
            if z+t >= length or a >= ri:
                raise ValueError('Each baffle must lie strictly inside tube length and have aperture_radius_mm < inner_radius_mm.')
            rings.append((z, t, a))
        rings.sort()
        if any(rings[i][0] < rings[i-1][0]+rings[i-1][1] for i in range(1, len(rings))):
            raise ValueError('Baffle axial intervals must not overlap.')
        part = cq.Workplane('XY').circle(ro).circle(ri).extrude(length)
        for z, t, a in rings:
            ring = cq.Workplane('XY').circle(ro).circle(a).extrude(t).translate((0, 0, z))
            part = part.union(ring)
        analytic = math.pi*(ro*ro-ri*ri)*length + sum(math.pi*(ri*ri-a*a)*t for _, t, a in rings)
        bounds = [-ro, ro, -ro, ro, 0., length]
    else:
        raise ValueError(f'Unknown part type: {kind}; use rectangular_mount or baffle_tube.')
    return part.val(), analytic, bounds


def read_matrix(location):
    tr = location.wrapped.Transformation()
    return [[tr.Value(i, j) for j in range(1, 5)] for i in range(1, 4)] + [[0., 0., 0., 1.]]


def placement(item):
    import cadquery as cq
    import numpy as np
    from OCP.gp import gp_Trsf
    if 'matrix' in item:
        keys(item, ['part', 'matrix'])
        values = item['matrix']
        if not isinstance(values, list) or len(values) != 4:
            raise ValueError('matrix must be a 4x4 rigid transform.')
        matrix = np.array([vector(row, 'matrix row', 4) for row in values])
        rotation = matrix[:3, :3]
        if not np.allclose(matrix[3], [0, 0, 0, 1], rtol=0, atol=1e-12):
            raise ValueError('Rigid matrix last row must be [0,0,0,1].')
        if not np.allclose(rotation.T@rotation, np.eye(3), rtol=0, atol=1e-12) or abs(np.linalg.det(rotation)-1) > 1e-12:
            raise ValueError('matrix rotation must be orthonormal with determinant +1; scale/shear/reflection rejected.')
        tr = gp_Trsf()
        tr.SetValues(*matrix[:3, :].ravel().tolist())
        location = cq.Location(tr)
        expected = matrix.tolist()
    else:
        keys(item, ['part', 'translation_mm', 'axis', 'angle_deg'])
        translation = vector(item['translation_mm'], 'translation_mm', 3)
        axis = np.array(vector(item['axis'], 'axis', 3))
        angle = number(item['angle_deg'], 'angle_deg')
        norm = float(np.linalg.norm(axis))
        if norm <= 1e-15:
            raise ValueError('Rotation axis must be nonzero, including for angle 0.')
        axis /= norm
        location = cq.Location(cq.Vector(*translation), cq.Vector(*axis), angle)
        # Independent Rodrigues formula: active right-handed local-to-world rotation.
        x, y, z = axis
        skew = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
        theta = math.radians(angle)
        rotation = math.cos(theta)*np.eye(3)+(1-math.cos(theta))*np.outer(axis, axis)+math.sin(theta)*skew
        expected = np.eye(4)
        expected[:3, :3] = rotation
        expected[:3, 3] = translation
        expected = expected.tolist()
    actual = read_matrix(location)
    rerr = max(abs(actual[i][j]-expected[i][j]) for i in range(3) for j in range(3))
    terr = max(abs(actual[i][3]-expected[i][3]) for i in range(3))
    if rerr > 1e-12 or terr > 1e-9:
        raise RuntimeError('CadQuery Location readback differs from supplied rigid transform.')
    return location, expected


def exchange(shape, stem, out):
    import cadquery as cq
    before = measure(shape)
    step, stl = out / f'{stem}.step', out / f'{stem}.stl'
    cq.exporters.export(shape, str(step))
    after_shape = cq.importers.importStep(str(step)).val()
    after = measure(after_shape)
    verror = abs(after['volume_mm3']/before['volume_mm3']-1.)
    berror = max(abs(a-b) for a, b in zip(before['bounds_mm'], after['bounds_mm']))
    cq.exporters.export(shape, str(stl), tolerance=.05, angularTolerance=.1)
    raw = stl.read_bytes()
    if len(raw) < 84:
        raise RuntimeError('STL file is too short for binary STL.')
    triangles = struct.unpack('<I', raw[80:84])[0]
    checks = {'step_volume_relative_le_1e_8': verror <= 1e-8,
              'step_bounds_abs_le_1e_6_mm': berror <= 1e-6,
              'step_valid': after['valid'], 'step_solid_count': after['solid_count'] == before['solid_count'],
              'binary_stl_length': triangles > 0 and len(raw) == 84+50*triangles}
    result = {'step': step.name, 'stl': stl.name, 'step_sha256': sha(step.read_bytes()), 'stl_sha256': sha(raw),
              'step_readback': after, 'step_volume_relative_error': verror, 'step_bounds_max_abs_error_mm': berror,
              'stl_triangles': triangles, 'stl_bytes': len(raw), 'checks': checks}
    if not all(checks.values()):
        raise RuntimeError(f'STEP/STL exchange gate failed for {stem}: {checks}')
    return result


def build(data, out):
    import cadquery as cq
    import numpy as np
    keys(data, ['units', 'parts'], ['assembly'])
    if data['units'] != 'mm':
        raise ValueError('units must be mm.')
    if not isinstance(data['parts'], list) or not data['parts']:
        raise ValueError('parts must be a nonempty list.')
    shapes, results = {}, []
    for p in data['parts']:
        if not isinstance(p, dict) or not isinstance(p.get('name'), str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]*', p['name']):
            raise ValueError('Part name must start with ASCII letter and contain only letters, digits, _ or -.')
        name = p['name']
        reserved = {'assembly', 'assembly-flat', 'con', 'prn', 'aux', 'nul'} | {f'{prefix}{i}' for prefix in ('com', 'lpt') for i in range(1, 10)}
        if name.lower() in reserved or name.lower() in {n.lower() for n in shapes}:
            raise ValueError('Part names must be unique ignoring case and avoid assembly, assembly-flat and Windows device names.')
        if 'type' not in p:
            raise ValueError('Each part requires type.')
        shape, analytic, bounds = make_part(p)
        values = measure(shape)
        verror = abs(values['volume_mm3']/analytic-1.)
        berror = max(abs(a-b) for a, b in zip(values['bounds_mm'], bounds))
        checks = {'valid_single_solid': values['valid'] and values['solid_count'] == 1,
                  'analytic_volume_relative_le_1e_9': verror <= 1e-9,
                  'bounds_abs_le_1e_6_mm': berror <= 1e-6}
        if not all(checks.values()):
            raise RuntimeError(f'Part geometry gate failed for {name}: {checks}')
        shapes[name] = shape
        results.append({'name': name, 'type': p['type'], 'parameters': p, 'geometry': values,
                        'analytic_volume_mm3': analytic, 'analytic_volume_relative_error': verror,
                        'bounds_max_abs_error_mm': berror, 'checks': checks})
    assy = None
    assembly_report = None
    if 'assembly' in data:
        keys(data['assembly'], ['placements'])
        items = data['assembly']['placements']
        if not isinstance(items, list) or len(items) != len(shapes):
            raise ValueError('assembly.placements must place every part exactly once.')
        if any(not isinstance(item, dict) or not isinstance(item.get('part'), str) for item in items):
            raise ValueError('Every placement requires a part name.')
        if {item['part'] for item in items} != set(shapes):
            raise ValueError('assembly.placements must use all part names exactly once.')
        assy = cq.Assembly(name='assembly')
        poses = []
        for item in items:
            loc, expected = placement(item)
            name = item['part']
            assy.add(shapes[name], name=name, loc=loc)
            node = assy.objects[name]
            actual = read_matrix(node.loc)
            moved_center = list(node.obj.moved(node.loc).Center().toTuple())
            expected_center = (np.array(expected)@np.array([*shapes[name].Center().toTuple(), 1]))[:3]
            center_error = float(max(abs(np.array(moved_center)-expected_center)))
            rerr = max(abs(actual[i][j]-expected[i][j]) for i in range(3) for j in range(3))
            terr = max(abs(actual[i][3]-expected[i][3]) for i in range(3))
            if rerr > 1e-12 or terr > 1e-9 or center_error > 1e-9:
                raise RuntimeError(f'Assembly tree/placed solid pose readback failed for {name}.')
            poses.append({'part': name, 'matrix_local_to_world': actual, 'expected_matrix': expected,
                          'rotation_max_abs_error': rerr, 'translation_max_abs_error_mm': terr,
                          'placed_center_mm': moved_center, 'center_max_abs_error_mm': center_error})
        compound = assy.toCompound()
        if len(compound.Solids()) != len(shapes):
            raise RuntimeError('Assembly materialization lost solids.')
        assembly_report = {'poses': poses, 'geometry': measure(compound),
                           'pose_source': 'CadQuery assembly tree Location and transformed solid centroid; not STEP hierarchy readback'}
    # Validate all requested geometry and placements before exporting any deliverables.
    for result in results:
        result['exchange'] = exchange(shapes[result['name']], result['name'], out)
    if assy is not None:
        # Keep named hierarchy STEP and a separately tested flattened STEP/STL.
        assy.export(str(out / 'assembly.step'))
        assembly_report['hierarchical_step'] = 'assembly.step'
        assembly_report['hierarchical_step_sha256'] = sha((out / 'assembly.step').read_bytes())
        assembly_report['flattened_exchange'] = exchange(assy.toCompound(), 'assembly-flat', out)
    return {'parts': results, 'assembly': assembly_report, 'units': 'mm',
            'stl_settings': {'linear_tolerance_mm': .05, 'angular_tolerance_rad': .1},
            'limitations': ['Nominal ideal solids; no tolerances, threads, fits, collision or clearance check.',
                            'Local XY-centered geometry with bottom at z=0; active right-handed rigid local-to-world poses.',
                            'Pose readback is from the actual assembly tree, not a STEP hierarchy roundtrip.',
                            'Flattened assembly STEP roundtrip checks B-rep geometry; STL is a triangulated exchange, not exact B-rep volume.',
                            'No automatic pose extraction from optical prescriptions or manufacturing qualification.']}


if __name__ == '__main__':
    sys.exit(execute(build))
