#!/usr/bin/env python3
"""Generate a deterministic route inventory, not a claim of live API parity."""
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from onshape_native.catalog import Catalog
from onshape_native.bridge import validate_job, BridgeError

catalog=Catalog();rows=[]
for name,(method,path,spec) in sorted(catalog.ops.items()):
    endpoint='/api/v17'+re.sub(r'\{[^}]+\}','sample',path)
    try:
        validate_job({'kind':'rest','method':method,'path':endpoint})
        route='available'
    except BridgeError as error:
        route='browser-owned authentication' if name=='session' else 'unsupported'
    multipart='multipart/form-data' in (catalog.schema(name).get('requestBody') or {}).get('content',{})
    rows.append({'operation':name,'method':method,'path':'/api/v17'+path,'route':route,
                 'body_transport':'multipart' if multipart else 'json-or-none',
                 'verification':'schema resolution and route validation only; see live-validation.json for executed workflows'})
report={'schema_version':json.loads((ROOT/'data/openapi.json').read_text())['info']['version'],
        'operation_count':len(rows),'routable_count':sum(x['route']=='available' for x in rows),
        'live_parity_verified':False,'operations':rows}
(ROOT/'docs/evidence/api-coverage.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='operations'}))
