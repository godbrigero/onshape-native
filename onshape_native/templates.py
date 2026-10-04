"""Build editable templates from the current server's feature specifications."""
from .client import OnshapeError


def template(spec):
    def clean(value):
        if isinstance(value, list): return [clean(x) for x in value]
        if isinstance(value, dict): return {k:clean(v) for k,v in value.items() if k != 'nodeId'}
        return value
    return {'btType':'BTMFeature-134', 'featureType':spec['featureType'],
            'name':spec.get('featureTypeName') or spec['featureType'],
            'namespace':spec.get('namespace',''), 'suppressed':False,
            'parameters':[clean(p['defaultValue']) for p in spec.get('parameters',[]) if p.get('defaultValue') is not None]}


async def discover(service, snapshot, feature_type='', namespace=''):
    data=service.snapshot_data(snapshot)
    key=(data['target']['did'],data['target']['eid'],data['microversion'],data['configuration'])
    cache=getattr(service,'feature_specs_cache',{})
    if key not in cache:
        raw=await service.call('getPartStudioFeatureSpecs',service.pinned(data))
        cache[key]=service.store.put(raw)['artifact']
        service.feature_specs_cache=cache
    raw=service.store.read(cache[key]);specs=raw['featureSpecs']
    if not feature_type:
        return {'specifications':cache[key], 'features':[{'feature_type':s['featureType'],'name':s.get('featureTypeName'),
                'namespace':s.get('namespace','')} for s in specs],
                'next':'Request an exact feature_type and namespace for defaults and parameter constraints.'}
    matches=[s for s in specs if s['featureType']==feature_type and s.get('namespace','')==namespace]
    if len(matches)!=1: raise OnshapeError('Feature type/namespace must match exactly one live specification. List them first.')
    return {'microversion':data['microversion'],'libraryVersion':raw.get('libraryVersion'),
            'template':template(matches[0]),'specification':matches[0],
            'next':'Resolve required geometry queries and set parameters, then feature(action=add). Defaults alone may not form valid geometry.'}
