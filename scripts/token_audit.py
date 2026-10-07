#!/usr/bin/env python3
"""Read-only context audit. No bridge calls, CAD mutations, or raw CAD exports.

uv run --project . --with-requirements scripts/audit-requirements.txt \
  python scripts/token_audit.py --validation-dir /tmp

Measures actual local discovery returns and production formatting of historical
artifacts. These are tokenizer benchmarks, not provider billing or traffic logs.
"""
from __future__ import annotations
import argparse, asyncio, collections, csv, hashlib, html, inspect, json, math
from pathlib import Path
import statistics, sys
from types import SimpleNamespace
import importlib.metadata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import tiktoken
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from onshape_native import server
from onshape_native.store import Store,compact
from onshape_native.catalog import Catalog
from onshape_native.display import Display
from onshape_native.structures import page_tree
from onshape_native.service import Service
from onshape_native.client import Settings
from onshape_native.discovery import MANUAL

ENC={name:tiktoken.get_encoding(name) for name in ('o200k_base','cl100k_base')}
def tokens(value,encoding='o200k_base'):
    return len(ENC[encoding].encode(value if isinstance(value,str) else compact(value),disallowed_special=()))
def percentile(values,p):
    values=sorted(values)
    if not values:return None
    i=(len(values)-1)*p;low=math.floor(i);high=math.ceil(i)
    return round(values[low]*(high-i)+values[high]*(i-low)) if high!=low else values[low]

class ReadOnlyStore(Store):
    def __init__(self,root):self.root=root
    def put(self,data,suffix='json'):
        raw=compact(data).encode() if suffix=='json' else data
        key=hashlib.sha256(raw).hexdigest()+'.'+suffix
        return {'artifact':key,'path':str((self.root/key).resolve()),'bytes':len(raw)}

# Each public tool is classified, including tools with no historical sample.
POLICIES={
 'resolve_target':'Direct JSON; tab candidate count is not globally token-capped.',
 'search_commands':'1–10 matches; repeated manual fallback + per-match invocation metadata; no character cap.',
 'browse_commands':'1–100 matches (default 10); repeated manual procedure; no character cap.',
 'document_tree':'Store.page: 7,000-character data check, default 20 rows; metadata outside cap.',
 'element_tree':'Store.page: 7,000-character data check, default 20 rows; metadata outside cap.',
 'document_history':'Default 20 scanned events; character paging and history metadata; not a token cap.',
 'document_edit':'Direct verified result + refreshed hierarchy; no universal total token cap.',
 'sidebar_edit':'Direct verified result + refreshed hierarchy; no universal total token cap.',
 'api_catalog':'Search: 10 summaries, 180 characters each. Schema: Store.response, 7,000-character data check.',
 'api_read':'Store.response; default 20 entries, 7,000-character data check, metadata outside cap.',
 'artifact_page':'Store.page; default 20 entries, 7,000-character data check; zero remote calls.',
 'inspect_model':'9,000-character precheck, then replaces large collections with retrieval hints; not token based.',
 'evaluate':'Store.response; nested evaluation results may require a narrower pointer.',
 'feature_template':'Store.response; nested parameter specifications may require a narrower pointer.',
 'feature':'1–20 edits; one acknowledgement/artifact per completed feature; no total token cap.',
 'api_write':'Store.response; raw response paged after write.',
 'sidebar_prepare':'Direct plan instructions and geometry baseline; no global output cap.',
 'sidebar_verify':'Store.response; observation may be up to 4,000 characters.',
 'render_views':'1–4 images in one contact sheet + metadata; image token cost is client/model dependent.',
 'bridge_status':'Direct health + all Onshape tab metadata; no global token cap.',
 'native_catalog':'Store.response; large nested defaults/examples may trigger pointer fallback.',
 'native_state':'Store.response; nested model tree may trigger pointer fallback.',
 'native_schema':'Store.response; nested defaults may trigger pointer fallback.',
 'native_read':'Store.response; bounded data, artifact metadata outside cap.',
 'native_write':'Store.response; bounded data, artifact metadata outside cap.',
 'api_upload':'Store.response; upload byte limit is not a response token limit.',
 'open_document':'Direct tab/open acknowledgement; no global token cap.',
 'ui_inspect':'Store.response; control metadata paged.',
 'ui_action':'Direct action acknowledgement/error; no global token cap.',
 'api_request':'Store.response for JSON; binary output is a file artifact.',
 'display_state':'Halves page size until data fits 7,000 characters; repeats full camera and metadata on every page.',
 'set_visibility':'1–100 changes; first 5 readback checks via Store.response + snapshot and guidance.',
 'mate_animation':'Direct session/status with target, angle explanation and verification on every call.',
 'view_control':'Direct full camera arrays and target on every action/read.',
 'capture_viewport':'Full camera/target/file metadata plus inline image; image cost excluded from text tokenizer.',
}

def lean(tool,data):
    """Counterfactual task-specific summaries; not production behavior changes."""
    if not isinstance(data,dict):return data
    d=dict(data)
    if tool in ('search_commands','browse_commands'):
        d={k:v for k,v in d.items() if k in ('matches','total','next_offset','low_confidence')}
        d['matches']=[{k:v for k,v in r.items() if k in ('source','name','summary','read_only','evidence','available','score','invoke','replay_verified')} for r in d['matches']]
        for r in d['matches']:
            # Invocation/schema details remain available via existing discovery.
            if 'summary' in r:r['summary']=r['summary'][:140]
            if r.get('source')=='tool':r.pop('invoke',None)
    elif tool=='display_state':
        d.pop('camera',None)
        if isinstance(d.get('data'),list):
            keep={'tree_path','parent_path','name','reference','effective_visible','visibility','parent_hidden','suppressed','suppressed_by_parent','inherited_connector','mate_type','reason'}
            d['data']=[{k:v for k,v in row.items() if k in keep and v is not None} for row in d['data']]
    elif tool in ('document_tree','element_tree'):
        d.pop('next',None)
        if isinstance(d.get('data'),list):
            keep={'id','name','kind','parent_id','index','element_type','occurrence_path','feature_id','reference','effective_visible','hidden','suppressed','fixed','placement','node_id','inherited_connector','mate_type','status'}
            d['data']=[{k:v for k,v in row.items() if k in keep} for row in d['data']]
    elif tool in ('view_control','capture_viewport'):
        # Existing view_control(read) is the opt-in camera detail route.
        d.pop('camera',None);d.pop('target',None);d.pop('path',None)
    elif tool=='mate_animation':
        d.pop('target',None);d.pop('angle_source',None);d.pop('angle_radians',None)
    elif tool=='set_visibility':
        d.pop('next',None)
        checks=d.get('checks')
        if d.get('verified') and isinstance(checks,dict):
            d['checks']={k:v for k,v in checks.items() if k in ('artifact','total','next_offset')}
            d['checked_count']=checks.get('total')
    else:
        d.pop('path',None);d.pop('artifact_path',None)
        # Byte size is retained for binary/image artifacts.
        if 'data' in d:d.pop('bytes',None)
    return d

async def run(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    store=ReadOnlyStore(args.artifacts.resolve())
    server.service=SimpleNamespace(store=store,catalog=Catalog())
    samples=[]; payloads=[]; errors=[]
    def add(tool,value,mode,variant='',request=None):
        text=value if isinstance(value,str) else compact(value)
        try:data=json.loads(text)
        except ValueError:data=text
        small=lean(tool,data)
        sample={'sample':len(samples)+1,'tool':tool,'mode':mode,'variant':variant,
                'utf8_bytes':len(text.encode()),'characters':len(text),
                'o200k_base':tokens(text),'cl100k_base':tokens(text,'cl100k_base'),
                'mcp_text_block_tokens':tokens({'type':'text','text':text}),
                'request_tokens':tokens(request) if request is not None else None,
                'projected_terse_tokens':tokens(small),
                'pointer_fallback':bool(isinstance(data,dict) and data.get('needs_narrower_pointer')),
                'rows':len(data['data']) if isinstance(data,dict) and isinstance(data.get('data'),list) else None}
        samples.append(sample);payloads.append(data)
        return sample
    definitions=[t.model_dump(exclude_none=True) for t in await server.mcp.list_tools()]
    assert set(POLICIES)=={t['name'] for t in definitions}
    schemas=[]
    for t in definitions:
        schemas.append({'tool':t['name'],'tokens':tokens(t),'cl100k_base':tokens(t,'cl100k_base'),
                        'description_tokens':tokens(t.get('description','')),'input_schema_tokens':tokens(t['inputSchema']),
                        'source_line':inspect.getsourcelines(getattr(server,t['name']))[1],'policy':POLICIES[t['name']]})
    queries=['create cube sketch extrude','create torus revolve','duplicate part studio','move tab into folder','show motor joints hide inherited connectors','animate lidar revolute mate','capture viewport screenshot','zoom to assembly selection','measure mass inertia weight','assign material density','add assembly instance','create revolute mate','fillet edges','hollow shell thickness','pattern features','export STEP file','inspect feature history','rename assembly','find face normal','edit sketch dimensions']
    for q in queries:
        add('search_commands',server.search_commands(q),'executed-local','top10',{'task':q})
        add('browse_commands',server.browse_commands(q.split()[0]),'executed-local','default10',{'query':q.split()[0]})
        add('api_catalog',server.api_catalog(search=q),'executed-local','search',{'search':q})
    for source in ['all','rest','native','tool']:
        for limit in [1,10,100]:add('browse_commands',server.browse_commands(source=source,limit=limit),'executed-local',f'{source};limit={limit}')
    for operation in ['getPartStudioFeatures','getAssemblyDefinition','getAssemblyMassProperties','getDocumentHistory','addPartStudioFeature','createAssembly','getElementsInDocument','getPartMassProperties']:
        if operation in server.service.catalog.ops:add('api_catalog',server.api_catalog(schema=operation),'executed-local','schema')
    for q in ['','visibility','AnimateMate','MassProp','CreateFolder','Sketch','Extrude']:
        add('native_catalog',server.native_catalog(q),'executed-local','search')
    docs=[];displays=[];snapshots=[];files=sorted(store.root.glob('*.json'))
    for file in files:
        try:d=json.loads(file.read_text())
        except (ValueError,OSError):continue
        if not isinstance(d,dict):continue
        kind=d.get('kind')
        if kind=='onshape-structure':
            if d.get('tree_kind')=='assembly' and not {'occurrences_complete','sidebar_complete'}<=d.keys():
                errors.append({'stage':'old-cache-skipped','error_type':'Pre-completeness assembly snapshot'})
                continue
            docs.append((file.name,d))
            tool='document_tree' if d['tree_kind']=='document' else 'element_tree'
            add(tool,page_tree(store,d,file.name),'cached-production-formatter',d['tree_kind']+';default20')
        elif kind=='onshape-display':
            displays.append((file.name,d))
            add('display_state',Display(server.service).page(d,file.name,0,20),'cached-production-formatter','default20')
            if 'checks' in d:
                result={'verified':d['verified'],'snapshot':file.name,'checks':store.response(d['checks'],limit=5),'microversion':d['microversion'],
                        'next':'Read display_state with this snapshot to page the observed state; omit snapshot for a new verification read.'}
                add('set_visibility',result,'cached-response-reconstruction','verified-batch')
        elif kind=='onshape-snapshot':snapshots.append((file.name,d))
        elif 'completed' in d and 'next' in d:add('feature',d,'recorded-response','batch')
        elif 'feature' in d and 'featureState' in d:add('api_write',store.response(d),'cached-production-formatter','feature-response')
        elif 'microversion_before' in d and 'result' in d:add('native_write',store.response(d),'cached-production-formatter','native-response')
        elif 'template' in d and 'specification' in d:add('feature_template',store.response(d),'cached-production-formatter','template')
        elif 'result' in d and 'microversion' in d and ('notices' in d or 'evaluation_failed' in d):add('evaluate',store.response(d),'cached-production-formatter','evaluation')
        elif 'tree' in d and 'microversion' in d:add('native_state',store.response(d),'cached-production-formatter','native-tree')
        elif 'name' in d and 'defaults' in d:add('native_schema',store.response(d),'cached-production-formatter','message-defaults')
        elif 'rootAssembly' in d:add('api_read',store.response(d),'cached-production-formatter','assembly-definition')
        elif 'features' in d and 'sourceMicroversion' in d:add('api_read',store.response(d),'cached-production-formatter','features')
        elif 'bodies' in d or ('mass' in d and 'inertia' in d):add('api_read',store.response(d),'cached-production-formatter','mass/topology')
        # Every saved response can be retrieved through the real artifact pager.
        if not kind and file.stat().st_size<2_000_000:
            add('artifact_page',store.page(d),'cached-production-formatter','root-default20')
    for file,d in snapshots:
        try:
            mock=Service.__new__(Service);mock.store=store;mock.settings=Settings(cache_dir=store.root)
            raw=store.read(d['feature_artifact'])
            async def call(operation,*a,**kw):
                if operation=='getPartStudioFeatures':return raw
                if operation=='getPartsWMVE':return [{'partId':p['id'],'name':p.get('name'),'bodyType':p.get('type')} for p in d.get('parts',[])]
                raise AssertionError(operation)
            async def evaluate(*a,**kw):return {'result':[{k:v for k,v in p.items() if k!='name'} for p in d.get('solids',[])]} if d.get('geometry_complete') else {'evaluation_failed':True}
            mock.call=call;mock.eval=evaluate
            add('inspect_model',await mock.inspect(d['url'],geometry=d['geometry_complete']),'cached-response-reconstruction','full')
            add('inspect_model',await mock.inspect(d['url'],geometry=d['geometry_complete'],previous=file),'cached-response-reconstruction','unchanged')
            add('resolve_target',server.resolve_context(d['url']) if hasattr(server,'resolve_context') else {},'executed-local','explicit-url')
        except Exception as e:errors.append({'stage':'inspect-reconstruction','error_type':type(e).__name__})
    # Optional original validation returns; no requests are sent or replayed.
    if args.validation_dir:
        p=args.validation_dir/'onshape-display-validation.json'
        if p.exists():
            validation=json.loads(p.read_text())
            for key,value in validation.items():
                if key.startswith('motion_'):add('mate_animation',value,'recorded-response',key.removeprefix('motion_'))
                elif key in ('camera_standard','camera_zoom','camera_restore'):add('view_control',value,'recorded-response',key.removeprefix('camera_'))
                elif key=='camera_capture':add('capture_viewport',value,'recorded-response','text-only;image-excluded')
    # Full traversal is simulated against one fixed largest snapshot per tree kind.
    traversals=[]
    selected={}
    for file,d in docs:
        key=d['tree_kind']
        if key not in selected or len(d['rows'])>len(selected[key][1]['rows']):selected[key]=(file,d)
    if displays:selected['display']=max(displays,key=lambda pair:len(pair[1]['rows']))
    for kind,(file,d) in selected.items():
        for initial in [1,5,10,20,50,100]:
            offset=0;limit=initial;cost=0;calls=0;fallbacks=0;rows=0
            while True:
                page=Display(server.service).page(d,file,offset,limit) if kind=='display' else page_tree(store,d,file,offset=offset,limit=limit)
                calls+=1;cost+=tokens(page)
                if page.get('needs_narrower_pointer'):
                    fallbacks+=1
                    if limit==1:break
                    limit=max(1,limit//2);continue
                rows+=len(page['data']);offset=page['next_offset']
                if offset is None:break
            traversals.append({'kind':kind,'initial_limit':initial,'rows':rows,'calls':calls,'fallbacks':fallbacks,'tokens':cost,'complete':rows==len(d['rows'])})
    # Field-ablation costs are not additive: JSON/token boundaries can merge.
    ablations=[]
    for tool,variant in [('search_commands','top10'),('display_state','default20'),('element_tree','assembly;default20'),('view_control','restore')]:
        candidates=[(s,d) for s,d in zip(samples,payloads) if s['tool']==tool and s['variant']==variant]
        if not candidates:continue
        s,d=sorted(candidates,key=lambda pair:pair[0]['o200k_base'])[len(candidates)//2]
        if isinstance(d,dict):
            for key in d:
                ablations.append({'tool':tool,'field':key,'whole_response_tokens':s['o200k_base'],'tokens_removed_if_omitted':s['o200k_base']-tokens({k:v for k,v in d.items() if k!=key})})
    grouped=collections.defaultdict(list)
    for sample in samples:grouped[sample['tool']].append(sample)
    coverage=[]
    for schema in schemas:
        group=grouped[schema['tool']];values=[s['o200k_base'] for s in group]
        coverage.append({**schema,'samples':len(group),'modes':sorted({s['mode'] for s in group}),
            'response_min':min(values) if values else None,'response_p50':percentile(values,.5),'response_p95':percentile(values,.95),'response_max':max(values) if values else None,
            'pointer_fallbacks':sum(s['pointer_fallback'] for s in group)})
    projections=[]
    for tool in ['search_commands','display_state','element_tree','document_tree','view_control','mate_animation','set_visibility','capture_viewport','feature','api_read']:
        group=[s for s in samples if s['tool']==tool and not s['pointer_fallback']]
        if not group:continue
        if tool=='search_commands':group=[s for s in group if s['variant']=='top10']
        before=sum(s['o200k_base'] for s in group)/len(group);after=sum(s['projected_terse_tokens'] for s in group)/len(group)
        projections.append({'tool':tool,'samples':len(group),'current_mean':round(before),'projected_mean':round(after),'reduction_percent':round(100*(before-after)/before,1)})
    variant_groups=collections.defaultdict(list)
    for s in samples:variant_groups[(s['tool'],s['variant'])].append(s)
    variants=[]
    for (tool,variant),group in sorted(variant_groups.items()):
        values=[s['o200k_base'] for s in group]
        variants.append({'tool':tool,'variant':variant,'samples':len(group),'median':percentile(values,.5),'p95':percentile(values,.95),'min':min(values),'max':max(values),'pointer_fallbacks':sum(s['pointer_fallback'] for s in group)})
    report={'method':{'date':'2026-10-07','primary_encoding':'o200k_base','sensitivity_encoding':'cl100k_base','exact_for':'Serialized text measured with the named tokenizer, not actual Codex/Claude billing.','corpus':'Historical artifact census, local discovery queries and optional recorded validation returns; not a production traffic sample.','raw_CAD_exported':False,'CAD_requests_sent':0,'image_tokens':'Not measured; neither base64 text tokens nor file bytes represent image context cost.','dependencies':{p:importlib.metadata.version(p) for p in ['tiktoken','matplotlib','mcp']},'artifact_files_scanned':len(files),'errors':errors},
        'schemas':{'total_tokens':tokens(definitions),'total_cl100k':tokens(definitions,'cl100k_base'),'count':len(definitions),'instructions_tokens':tokens(server.mcp.instructions),'skill_tokens':tokens((ROOT/'skills/onshape-native-modeling/SKILL.md').read_text()),'manual_fallback_tokens':tokens(MANUAL)},
        'coverage':coverage,'samples':samples,'variants':variants,'traversals':traversals,'field_ablations':ablations,'projections':projections,
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'onshape_native').glob('*.py'))}}
    (out/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    for name,rows in [('samples',samples),('tool-coverage',coverage),('variants',variants),('pagination',traversals),('field-ablations',ablations),('projections',projections)]:
        if rows:
            with (out/(name+'.csv')).open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
    draw(report,out)
    write_report(report,out)
    print(json.dumps({'output':str(out),'samples':len(samples),'tools_measured':sum(bool(g) for g in grouped.values()),'tools_audited':len(coverage),'schema_tokens':report['schemas']['total_tokens'],'errors':errors,'top_responses':sorted([{'tool':r['tool'],'p50':r['response_p50'],'p95':r['response_p95'],'n':r['samples']} for r in coverage if r['samples']],key=lambda x:x['p50'],reverse=True)[:10],'projections':projections}))

def draw(report,out):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','figure.facecolor':'#f8fafc','axes.facecolor':'#f8fafc','savefig.facecolor':'#f8fafc'})
    def save(fig,name):
        fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=160,bbox_inches='tight');fig.savefig(out/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    rows=sorted(report['coverage'],key=lambda r:r['tokens'])
    fig,ax=plt.subplots(figsize=(12,12));bars=ax.barh([r['tool'] for r in rows],[r['tokens'] for r in rows],color='#2563eb')
    ax.bar_label(bars,padding=4,fontsize=8);ax.set_xlim(0,max(r['tokens'] for r in rows)*1.13);ax.set_xlabel('o200k_base tokens per serialized tool definition')
    ax.set_title(f"35 tool definitions: {report['schemas']['total_tokens']:,} tokens in the full list\nAvailability in the model context depends on client tool loading",loc='left',pad=15);save(fig,'01-tool-definitions')
    rows=sorted([r for r in report['coverage'] if r['samples']],key=lambda r:r['response_p50'])
    fig,ax=plt.subplots(figsize=(12,9))
    for i,r in enumerate(rows):
        ax.plot([max(1,r['response_min']),r['response_max']],[i,i],color='#cbd5e1',linewidth=4)
        ax.scatter(r['response_p95'],i,color='#f59e0b',s=42,zorder=3)
        ax.scatter(r['response_p50'],i,color='#2563eb',s=46,zorder=4)
    ax.set_yticks(range(len(rows)),[f"{r['tool']}  (n={r['samples']})" for r in rows]);ax.set_xscale('log');ax.set_xlabel('Text-response tokens • log scale • blue median / amber p95 / gray min–max')
    ax.set_title('Response cost varies greatly by tool and payload\nCorpus percentiles are not production-traffic percentiles; images excluded',loc='left',pad=15);ax.grid(axis='x',alpha=.2);save(fig,'02-response-distribution')
    fig,axes=plt.subplots(2,2,figsize=(14,9))
    for ax,tool in zip(axes.flat,['search_commands','display_state','element_tree','view_control']):
        data=sorted([a for a in report['field_ablations'] if a['tool']==tool],key=lambda a:a['tokens_removed_if_omitted'])[-7:]
        ax.barh([r['field'] for r in data],[r['tokens_removed_if_omitted'] for r in data],color='#0d9488');ax.set_title(tool,loc='left');ax.set_xlabel('Tokens removed by omitting this field');ax.grid(axis='x',alpha=.15)
    fig.suptitle('Where response tokens go • field ablations, not additive shares',fontsize=16,x=.05,ha='left');save(fig,'03-field-costs')
    fig,axes=plt.subplots(1,2,figsize=(14,5.5))
    for kind in sorted({r['kind'] for r in report['traversals']}):
        data=[r for r in report['traversals'] if r['kind']==kind]
        for ax,key in zip(axes,['tokens','calls']):ax.plot([r['initial_limit'] for r in data],[r[key] for r in data],marker='o',label=f"{kind} ({max(r['rows'] for r in data)} rows)")
    for ax in axes:ax.set_xscale('log');ax.set_xlabel('Requested rows per page');ax.set_xticks([1,5,10,20,50,100],labels=['1','5','10','20','50','100']);ax.grid(alpha=.15);ax.legend(fontsize=8)
    axes[0].set_ylabel('Total response tokens for complete traversal');axes[1].set_ylabel('Calls, including narrower-pointer retries');fig.suptitle('Small pages can cost more overall • simulated traversal of fixed snapshots',fontsize=15);save(fig,'04-pagination')
    rows=sorted(report['projections'],key=lambda r:r['current_mean'])
    fig,ax=plt.subplots(figsize=(12,7));y=list(range(len(rows)))
    ax.barh([i+.18 for i in y],[r['current_mean'] for r in rows],height=.34,label='Current measured mean',color='#2563eb')
    ax.barh([i-.18 for i in y],[r['projected_mean'] for r in rows],height=.34,label='Proposed task-specific summary',color='#0d9488')
    ax.set_yticks(y,[f"{r['tool']}  (−{r['reduction_percent']}%)" for r in rows]);ax.set_xlabel('Text tokens per response');ax.legend();ax.set_title('Counterfactual savings on the same non-fallback response samples\nNot implemented; omitted details must remain available on demand',loc='left');save(fig,'05-projected-savings')
    # An explicit, editable workload assumption, not observed production usage.
    assumptions={'search_commands':5,'document_tree':3,'element_tree':8,'display_state':10,'view_control':6,'mate_animation':12,'set_visibility':2,'capture_viewport':2}
    costs={r['tool']:r for r in report['projections']};points=[]
    for tool,n in assumptions.items():
        if tool in costs:points.append((tool,n,n*costs[tool]['current_mean'],n*costs[tool]['projected_mean']))
    points.sort(key=lambda r:r[2]);fig,ax=plt.subplots(figsize=(12,6))
    ax.barh([f'{t} × {n}' for t,n,_,_ in points],[a for _,_,a,_ in points],color='#2563eb',label='Current')
    ax.barh([f'{t} × {n}' for t,n,_,_ in points],[b for _,_,_,b in points],color='#0d9488',label='Projected summary')
    ax.set_xlabel('Cumulative text response tokens');ax.legend();ax.set_title(f'Illustrative assembly workflow: {sum(n for _,n,_,_ in points)} calls\nFrequency assumptions are editable in the HTML report; image tokens excluded',loc='left');save(fig,'06-workflow')
    fig,axes=plt.subplots(1,2,figsize=(14,6))
    rows=sorted([r for r in report['coverage'] if r['pointer_fallbacks']],key=lambda r:r['pointer_fallbacks']/r['samples'])
    axes[0].barh([r['tool'] for r in rows],[100*r['pointer_fallbacks']/r['samples'] for r in rows],color='#d97706')
    axes[0].set_xlabel('Narrower-pointer responses / sampled calls (%)');axes[0].set_xlim(0,100);axes[0].set_title('A cheap reply may contain no requested data',loc='left')
    iv=[r for r in report['variants'] if r['tool']=='inspect_model']
    bars=axes[1].bar([r['variant'] for r in iv],[r['median'] for r in iv],color=['#2563eb','#0d9488']);axes[1].bar_label(bars,padding=4)
    axes[1].set_ylabel('Median response tokens');axes[1].set_ylim(0,max((r['median'] for r in iv),default=1)*1.2);axes[1].set_title('Existing unchanged-snapshot fast path',loc='left')
    fig.suptitle('Interpret low token counts carefully • selected corpus, not real traffic',fontsize=15);save(fig,'07-fallbacks-and-deltas')
    report['workflow']={'assumptions':{t:n for t,n,_,_ in points},'current':sum(a for _,_,a,_ in points),'projected':sum(b for _,_,_,b in points)}
    # Chart-derived workload is written back into the machine-readable record.
    (out/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')

def write_report(r,out):
    coverage=r['coverage'];by={row['tool']:row for row in coverage};projections={row['tool']:row for row in r['projections']}
    fmt=lambda x:'—' if x is None else f'{x:,}'
    table='\n'.join(f"| `{x['tool']}` | {x['tokens']} | {x['samples']} | {fmt(x['response_p50'])} | {fmt(x['response_p95'])} | {fmt(x['response_max'])} |" for x in sorted(coverage,key=lambda x:x['tool']))
    savings='\n'.join(f"| `{x['tool']}` | {x['current_mean']:,} | {x['projected_mean']:,} | {x['reduction_percent']}% |" for x in sorted(r['projections'],key=lambda x:x['current_mean']-x['projected_mean'],reverse=True))
    policy='\n'.join(f"- **{x['tool']}** ([source](../../onshape_native/server.py#L{x['source_line']})): {x['policy']}" for x in sorted(coverage,key=lambda x:x['tool']))
    missing=', '.join('`'+x['tool']+'`' for x in coverage if not x['samples'])
    fallback=sum(s['pointer_fallback'] for s in r['samples'])
    inspect_variants={v['variant']:v for v in r['variants'] if v['tool']=='inspect_model'}
    inspect_full=inspect_variants.get('full',{}).get('median','unmeasured')
    inspect_unchanged=inspect_variants.get('unchanged',{}).get('median','unmeasured')
    skipped=sum(e['stage']=='old-cache-skipped' for e in r['method']['errors'])
    usage_note='**Observed frequency is now available:** [two-thread frequency audit](usage/README.md) · [interactive frequency dashboard](usage/index.html). This supplements the artifact-size corpus with actual call counts; it does not treat cache files as invocation logs.\n' if (out/'usage/metrics.json').exists() else ''
    text=f'''# Onshape Native context audit

Measured 2026-10-07 against v0.4.0. **{len(r['samples']):,} text samples**, **{sum(bool(x['samples']) for x in coverage)}/35 tools with response samples**, all **35 tool definitions and output paths audited**. No CAD requests or mutations were made. Raw document content, IDs, screenshots and pairing credentials are not included in this report.

{usage_note}

## Findings

The tool does **not** enforce a fixed number of tokens per call. Most generic returns check a 7,000-character data payload, inspection checks 9,000 characters, and some tools bound only row counts. Metadata, camera arrays, instructions and client framing are outside these checks. A response that is small in bytes can still be expensive in tokens because of IDs, matrices and JSON structure.

The complete tool-definition list is **{r['schemas']['total_tokens']:,} o200k_base tokens**. Server instructions add **{r['schemas']['instructions_tokens']:,}**, and the modeling skill is **{r['schemas']['skill_tokens']:,}** when loaded. These are separate context surfaces: clients may defer tools, cache prompts, wrap schemas differently or compact history. Do not add the entire definition list to every call, and do not confuse cache discounts with fewer context tokens.

A ten-result command search repeats a **{r['schemas']['manual_fallback_tokens']:,}-token manual procedure**, plus engine/index/score explanations and verbose invocation records. Display pages repeat a full camera even when only visibility is requested. Structure rows repeat URLs, ancestry, raw pointers and—in assemblies—transforms. Camera commands return full matrices even for a simple successful fit. These are the strongest targeted opportunities.

## Measurement method and limits

- Exact text tokenization uses [`tiktoken`](https://github.com/openai/tiktoken), `o200k_base`; `cl100k_base` is a sensitivity check. These are **not verified Codex or Claude billing counts** and do not imply those clients use these encodings. Versions are recorded in `metrics.json`.
- `samples.csv` measures returned compact JSON text before client-specific wrapping. It separately records a serialized MCP text-block token count, UTF-8 bytes and request tokens where arguments are known. Request-token gaps mean unknown, not zero. Full JSON-RPC wire envelopes are not assumed to enter model context.
- Discovery functions were executed locally. Historical artifacts were passed through production response formatters. Part Studio inspections and visibility acknowledgements were reconstructed from saved data; recorded motion/camera returns are labeled separately. No synthetic response is labeled as live. Existing artifact contents are not modified by the audit.
- Percentiles describe this **selected corpus**, not actual usage frequency. Content-addressed storage deduplicates identical responses and overrepresents past research workflows. Frequency recommendations are hypotheses until client telemetry exists.
- No token count is assigned to images. An inline image is not ordinary base64 text in model context. `capture_viewport` counts only its metadata; `render_views` has no sampled return. Image dimensions/detail/client processing need separate measurement.
- Large raw artifacts are **not** equated with model-visible output. The actual paging/refusal result is measured. There were **{fallback} pointer-fallback responses** in this corpus; these contain little useful payload but can trigger extra calls.
- Response measurements remain missing for: {missing}. Their definitions and code paths were still reviewed. They are unknown, not free. There is no mutation replay to manufacture coverage. {skipped} assembly caches predating completeness fields were excluded from this run; skipped/reconstruction errors are recorded in `metrics.json`.

## Tool-definition overhead

![Every tool definition](01-tool-definitions.png)

`inputSchema`, descriptions, enum choices, defaults and annotations all contribute. Keep constraints necessary for safe use. Potential savings come from removing autogenerated schema titles/default boilerplate, using consistent concise descriptions, and testing client-supported deferred discovery. Returning ten candidates does not itself unload the 35 registered tool schemas.

## Per-tool response sizes

![Response distributions](02-response-distribution.png)

The range includes different operations and success/fallback variants. In particular, `inspect_model` combines full and unchanged snapshots, while `api_catalog` combines search and schema results. Use `variant` in the CSV to compare like with like. `browse_commands` includes explicit limits of 1, 10 and 100; its maximum is not the default-call cost.

![Fallbacks and unchanged reads](07-fallbacks-and-deltas.png)

`inspect_model` has a median of **{inspect_full} tokens for full reads** versus **{inspect_unchanged} for unchanged reads** in this corpus. Most raw assembly-definition reads and many feature-template root reads returned a narrower-pointer hint rather than data. These are measured results for naive default/root requests, not observed agent failure rates. Exact pointers and projections matter as much as shorter text. See `variants.csv` for separate distributions.

| Tool | Definition tokens | Samples | Median response | p95 | Maximum |
|---|---:|---:|---:|---:|---:|
{table}

## Repeated fields and pagination

![Field costs](03-field-costs.png)

Each bar removes one top-level field from a representative median response and retokenizes. Ablations are **not additive** because token boundaries change. Removing an entire `data` or `matches` field is diagnostic, not a recommendation to hide the information the agent needs.

![Pagination](04-pagination.png)

These traversals use one largest saved snapshot per kind, never fresh reads between pages. The simulated caller halves its requested limit after a narrower-pointer result and follows `next_offset`. `display_state` performs its own halving. Tiny pages often increase total cost by repeating snapshot IDs and metadata. A better design budgets tokens dynamically and fills each page efficiently, while preserving continuation pointers and completeness.

## Measured counterfactuals—not implemented optimizations

![Potential savings](05-projected-savings.png)

| Tool | Current mean | Proposed mean | Reduction |
|---|---:|---:|---:|
{savings}

The proposed summaries are task-specific views, not interchangeable lossless replacements. Search retains command names, evidence and routing, but moves manual instructions to the skill. Display drops the camera and duplicate row details. Tree browsing keeps hierarchy/IDs/status and makes transforms/URLs/raw pointers opt-in. Camera acknowledgements omit matrices unless requested. Motion drops repeated target/angle-source prose and duplicate angle units. Successful visibility batches keep aggregate verification and the checks artifact; failures must retain diagnostics. Generic replies omit local filesystem paths where an artifact handle suffices. Exact proposed projections are in `lean()` in the audit script.

**Never remove:** target disambiguation, freshness/revision guards, verification failures, partial completion, suppressed/hidden ancestor state, continuation pointers, or stable references needed for the next operation. A one-token “OK” cannot carry all of these. A concise success acknowledgement can, however, avoid hundreds of unrelated tokens.

## Workflow cost and optimization order

![Illustrative workflow](06-workflow.png)

The explicit **{sum(r['workflow']['assumptions'].values())}-call** scenario above produces **{r['workflow']['current']:,} current vs {r['workflow']['projected']:,} proposed text tokens**, using measured mean costs and assumed call counts. It excludes request arguments, schemas, skill loading, image tokens, model reasoning and client framing. It is a what-if estimate, not a traced task or a guaranteed reduction. The HTML calculator lets you change each frequency.

1. **Add response-only telemetry first.** Record tool, action, tokenizer/version, token/byte counts, latency, outcome and request variant; do not log raw model text, tokens/credentials or full URLs. Separate success, error, fallback and image metadata. Use real frequency × avoidable tokens to rank work.
2. **Make camera state opt-in and provide terse acknowledgements.** `display_state(include_camera=false)` and `view_control(detail="ack")` would remove the most obvious repeated numeric output. Preserve explicit camera readback for validation/save/restore.
3. **Slim discovery.** Keep ten useful results; return the fallback procedure only on request or low confidence. Avoid repeating schemas already exposed by MCP. Measure whether fewer candidates increases follow-up calls before changing the default.
4. **Add field projections and changed-since reads.** Browsing seldom needs 16-number transforms for every occurrence. Query visibility changes or requested references directly; retain full artifacts for details. Existing `inspect_model(previous=...)` already supplies a cheap unchanged result and should be used consistently.
5. **Implement a token-aware page budget.** For example, a configurable 600–1,200-token target for normal summaries, with an explicit override for schemas/topology. Charge envelope overhead first, pack rows to budget, and return exact continuation. Never truncate IDs, JSON or diagnostics. One oversized row should return a pointer and enough identity to fetch it.
6. **Reduce schema/skill overhead only after response hot spots.** Test a compact schema export and deferred tool loading in each client. Avoid consolidating tools so aggressively that agents repeatedly fetch giant schemas or choose the wrong operation.

Acceptance tests should compare task completion, total calls, total response tokens, failure-diagnostic preservation and reference correctness on the same frozen fixtures. Target a reduction in **whole-task** tokens, not merely a smaller first response. Add separate limits for errors and notices, whose source text can bypass a nominal success budget.

## Complete output-path inventory

{policy}

## Reproduce

From `onshape-native`, run:

```sh
uv run --project . --with-requirements scripts/audit-requirements.txt \\
  python scripts/token_audit.py --validation-dir /tmp
```

The validation directory is optional; without its existing motion/camera validation JSON, those sample categories are omitted. Use `--artifacts PATH` for a different local cache and `--output PATH` for a separate report. Dependencies are audit-only; the MCP runtime and response formats are unchanged. The report stores counts, tool names and source hashes only. Repeated runs may differ if the underlying artifact corpus changes.

Files: `metrics.json`, `samples.csv`, `tool-coverage.csv`, `variants.csv`, `pagination.csv`, `field-ablations.csv`, `projections.csv`, seven PNG/SVG charts, and `index.html`. The HTML works offline and includes sortable per-tool measurements and an editable workload calculator.
'''
    (out/'README.md').write_text(text)
    data=json.dumps({'coverage':coverage,'projections':r['projections'],'workflow':r['workflow'],'schema_tokens':r['schemas']['total_tokens']}).replace('<','\\u003c')
    cards=''.join(f'<section><h2>{title}</h2><a href="{name}.svg"><img src="{name}.png" alt="{title}"></a></section>' for name,title in [('01-tool-definitions','Tool-definition overhead'),('02-response-distribution','Response distributions'),('07-fallbacks-and-deltas','Fallbacks and unchanged reads'),('03-field-costs','Repeated fields'),('04-pagination','Pagination tradeoffs'),('05-projected-savings','Proposed summaries'),('06-workflow','Illustrative workflow')])
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Onshape Native · Context audit</title>
<style>body{font:16px/1.55 system-ui;background:#f8fafc;color:#17233b;max-width:1180px;margin:40px auto;padding:0 24px}h1{font-size:38px;line-height:1.15}h2{margin-top:0}section{background:white;border:1px solid #dae2ed;border-radius:14px;margin:24px 0;padding:24px}img{width:100%;height:auto}a{color:#2563eb}small,.muted{color:#526079}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;border-bottom:1px solid #e2e8f0;padding:9px}th button{border:0;background:transparent;font:inherit;font-weight:700;cursor:pointer}input{padding:8px;border:1px solid #bbc8d9;border-radius:5px}input[type=number]{width:72px}.banner{background:#e7f0ff;padding:18px;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}.stat{font-size:28px;font-weight:700}.scroll{overflow-x:auto}</style>
<h1>Onshape Native<br>Where the context goes</h1><p class="muted">v0.4.0 · 7 October 2026 · Read-only audit</p>
<div class="banner"><strong>Measured text, not provider billing.</strong> Counts use o200k_base. Cached response formatting and local discovery are measured; no CAD edits were performed. Images, client framing and hidden model context are excluded. Corpus percentiles do not measure production frequency.</div>
<p><a href="README.md">Full analysis and method</a> · <a href="samples.csv">Response CSV</a> · <a href="metrics.json">Machine-readable results</a></p>
<section><h2>Explore all 35 tools</h2><input id="filter" placeholder="Filter by tool name" aria-label="Filter by tool name"><p class="muted">Click a column heading to sort. A dash means no response sample, not zero cost. Schema cost is separate from response cost.</p><div class="scroll"><table><thead><tr><th><button data-key="tool">Tool ↕</button></th><th><button data-key="tokens">Schema ↕</button></th><th><button data-key="samples">Samples ↕</button></th><th><button data-key="response_p50">Median ↕</button></th><th><button data-key="response_p95">p95 ↕</button></th><th><button data-key="response_max">Max ↕</button></th></tr></thead><tbody id="tools"></tbody></table></div></section>
<section><h2>Build your own workload estimate</h2><p>Call counts below are assumptions. Costs use measured means; proposed summaries are not implemented. Text outputs only. No image cost is included.</p><div id="inputs" class="grid"></div><p id="totals" class="stat" aria-live="polite"></p><small>Schema list size: <span id="schema"></span> tokens, separate from this total. Whether all schemas are in context depends on client loading.</small></section>
CARDS
<script>const D=DATA;let key='response_p50',direction=-1;const fmt=n=>n==null?'—':Math.round(n).toLocaleString();function table(){let rows=D.coverage.filter(r=>r.tool.includes(document.querySelector('#filter').value.toLowerCase())).sort((a,b)=>typeof a[key]==='string'?direction*a[key].localeCompare(b[key]):direction*((a[key]??-1)-(b[key]??-1)));document.querySelector('#tools').innerHTML=rows.map(r=>'<tr>'+['tool','tokens','samples','response_p50','response_p95','response_max'].map(k=>'<td>'+ (k==='tool'?r.tool:fmt(r[k]))+'</td>').join('')+'</tr>').join('')}document.querySelector('#filter').oninput=table;document.querySelectorAll('button[data-key]').forEach(b=>b.onclick=()=>{direction=key===b.dataset.key?-direction:-1;key=b.dataset.key;table()});table();document.querySelector('#schema').textContent=fmt(D.schema_tokens);document.querySelector('#inputs').innerHTML=D.projections.map(r=>'<label>'+r.tool+' <input type="number" min="0" max="10000" step="1" data-tool="'+r.tool+'" value="'+(D.workflow.assumptions[r.tool]||0)+'"></label>').join('');function totals(){let a=0,b=0;document.querySelectorAll('input[data-tool]').forEach(i=>{let n=Math.min(10000,Math.max(0,Number(i.value)||0)),r=D.projections.find(r=>r.tool===i.dataset.tool);a+=n*r.current_mean;b+=n*r.projected_mean});document.querySelector('#totals').textContent=fmt(a)+' → '+fmt(b)+' tokens ('+(a?Math.round(100*(a-b)/a):0)+'% lower)'}document.querySelectorAll('input[data-tool]').forEach(i=>i.oninput=totals);totals();</script></html>'''.replace('CARDS',cards).replace('DATA',data)
    if (out/'usage/metrics.json').exists():
        page=page.replace('<h1>','<p><a href="usage/index.html"><strong>New: actual command frequencies and weighted costs from two threads →</strong></a></p><h1>',1)
    (out/'index.html').write_text(page)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,default=ROOT/'.runtime/artifacts')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/token-audit')
    parser.add_argument('--validation-dir',type=Path)
    asyncio.run(run(parser.parse_args()))
