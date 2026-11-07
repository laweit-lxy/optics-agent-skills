"""Qualified local RayOptics catalog and F-number policy, version 2.

Named glasses resolve only by exact name in the declared GCAT order. Runtime
patches are confined to this process and restored in finally. Working F-number
is evaluated only for supported centered on-axis systems; unsupported geometry
is reported explicitly rather than compared to an incompatible quantity.
"""
from contextlib import contextmanager
import math

class CatalogResolutionError(ValueError):pass

@contextmanager
def declared_catalog_import(audit):
    from rayoptics.zemax import zmxread
    from opticalglass import glassfactory,glasserror
    from rayoptics.util.misc_math import isanumber
    original=zmxread.ZmxGlassHandler
    class StrictDeclaredCatalogHandler(original):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.declared_catalogs=[]
        def __call__(self,sm,cur,cmd,inputs):
            if cmd=='GCAT':
                self.declared_catalogs=inputs.split()
                return super().__call__(sm,cur,cmd,inputs)
            if cmd!='GLAS':return super().__call__(sm,cur,cmd,inputs)
            fields=inputs.split();name=fields[0]
            if name in {'MIRROR','___BLANK'} or isanumber(name):return super().__call__(sm,cur,cmd,inputs)
            if not self.declared_catalogs:raise CatalogResolutionError('Named glass has no declared GCAT: '+name)
            attempted=[]
            for catalog in self.declared_catalogs:
                try:medium=glassfactory.create_glass(name,catalog)
                except glasserror.GlassError as e:attempted.append({'catalog':catalog,'error':type(e).__name__});continue
                if medium.name().casefold()!=name.casefold():raise CatalogResolutionError('Exact-name resolution failed')
                sm.gaps[cur].medium=medium;self.track_contents['glass found']+=1
                nd=float(medium.rindex(587.5618));nf=float(medium.rindex(486.1327));nc=float(medium.rindex(656.2725))
                audit.append({'surface':cur,'declared_name':name,'declared_catalogs':list(self.declared_catalogs),'resolved_name':medium.name(),'resolved_catalog':medium.catalog_name(),'resolved_nd':nd,'resolved_vd':(nd-1)/(nf-nc),'GLAS_nd':float(fields[3]) if len(fields)>3 else None,'GLAS_vd':float(fields[4]) if len(fields)>4 else None,'attempted':attempted})
                return True
            raise CatalogResolutionError('No exact glass '+name+' in declared catalogs '+repr(self.declared_catalogs))
    zmxread.ZmxGlassHandler=StrictDeclaredCatalogHandler
    try:yield
    finally:zmxread.ZmxGlassHandler=original

def on_axis_working_fnumber(model,wavelength_nm):
    """Native-compatible real-ray definition for centered on-axis test cases.

    Trace chief plus four pupil-edge rays, with vignetting and without aperture
    clipping. Off-axis and decentered generalizations are outside the qualified scope.
    """
    import numpy as np
    from rayoptics.raytr import trace
    sm=model['sm'];osp=model['osp']
    fld=next((f for f in osp['fov'].fields if abs(f.x)<=1e-14 and abs(f.y)<=1e-14),None)
    if fld is None:raise ValueError('On-axis field required')
    if any(getattr(i,'decenter',None) is not None for i in sm.ifcs):raise ValueError('Centered system required')
    def direction(pupil):
        pkg,err=trace.trace_ray(model,pupil,fld,wavelength_nm,check_apertures=False,apply_vignetting=True)
        if err is not None:raise ValueError('Marginal ray trace error: '+str(err))
        last=pkg.ray[-1] if hasattr(pkg,'ray') else pkg[0][-1]
        d=np.asarray(last.d if hasattr(last,'d') else last[1],dtype=float)
        return d/np.linalg.norm(d)
    chief=direction([0.,0.]);n_img=float(sm.gaps[-1].medium.rindex(wavelength_nm));rays=[]
    for pupil in [[0.,1.],[0.,-1.],[1.,0.],[-1.,0.]]:
        d=direction(pupil);sin2=max(0.,1.-float(np.dot(chief,d))**2)
        rays.append({'pupil':pupil,'image_direction':d.tolist(),'na_squared':n_img*n_img*sin2})
    na=math.sqrt(sum(r['na_squared'] for r in rays)/4)
    if na<=0:raise ValueError('Nonpositive real numerical aperture')
    return {'definition':'1/(2*n_image*sin(theta)), on-axis centered four-ray NA-squared mean','wavelength_nm':wavelength_nm,'working_f_number':1/(2*na),'image_index':n_img,'rays':rays}
