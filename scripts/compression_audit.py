#!/usr/bin/env python3
"""Replay saved responses through production compression; no Onshape/network calls."""
import argparse
import collections
import csv
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tiktoken
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from usage_audit import parse_thread, variant
from onshape_native.responses import respond, tree_page
from onshape_native.store import Store, compact

ENC = tiktoken.get_encoding('o200k_base')

def tokens(value):
    return len(ENC.encode(value if isinstance(value, str) else compact(value), disallowed_special=()))

class MemoryStore(Store):
    """Production paging with artifacts retained only in memory."""
    def __init__(self):
        self.values = {}
    def put(self, value, suffix='json'):
        raw = compact(value).encode()
        handle = hashlib.sha256(raw).hexdigest() + '.json'
        self.values[handle] = value
        return {'artifact':handle, 'path':'/offline/' + handle, 'bytes':len(raw)}

def recover(cache, handle, envelope=None):
    if not isinstance(handle,str) or len(handle)!=69 or not handle.endswith('.json'):
        return None, 'missing raw response'
    path = cache / handle
    if path.is_file():
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest()+'.json' != handle:
            return None, 'cache hash mismatch'
        return json.loads(raw), 'verified cache'
    if isinstance(envelope,dict) and 'data' in envelope and not envelope.get('needs_narrower_pointer') and envelope.get('next_offset') is None:
        value=envelope['data']
        if hashlib.sha256(compact(value).encode()).hexdigest()+'.json' == handle:
            return value, 'complete exported value'
    return None, 'missing raw response'

def replay(tool,args,old,cache,store):
    """Return production-formatted result plus the exact raw-input provenance."""
    if tool in ('search_commands','browse_commands'):
        return respond(store,old,args.get('detail','summary'),'discovery'), 'exported discovery'
    if tool in ('api_read','api_write') or tool=='api_catalog' and args.get('schema'):
        raw,source=recover(cache,old.get('artifact'),old)
        if raw is None:return None,source
        kind={'api_read':'read','api_write':'write','api_catalog':'schema'}[tool]
        return respond(store,raw,args.get('detail','summary'),kind,args.get('pointer',''),args.get('offset',0),args.get('limit',20)),source
    if tool=='artifact_page':
        raw,source=recover(cache,args.get('artifact'))
        if raw is None:return None,source
        return store.page(raw,args.get('pointer',''),args.get('offset',0),args.get('limit',20)),source
    if tool in ('document_tree','element_tree'):
        handle=old.get('snapshot') or args.get('snapshot')
        raw,source=recover(cache,handle)
        if raw is None:return None,source
        store.values[handle]=raw
        return tree_page(store,raw,handle,args.get('parent_id',''),args.get('recursive',True),args.get('offset',0),args.get('limit',20),args.get('query',''),args.get('node_id',''),args.get('detail','summary')),source
    return None,'unchanged tool'

def expansion_cost(store,handle,pointer):
    """Retrieve the entire indicated section, counting every page and child call."""
    raw=store.values[handle]
    calls=output=input_tokens=0
    pending=[pointer]
    while pending:
        pointer=pending.pop()
        offset=0
        while offset is not None:
            args={'artifact':handle,'pointer':pointer,'offset':offset,'limit':20}
            page=store.page(raw,pointer,offset,20)
            calls+=1;output+=tokens(page);input_tokens+=tokens(args)
            if page.get('needs_narrower_pointer'):
                pending.extend(c['pointer'] for c in page['children'])
            offset=page.get('next_offset')
    return {'calls':calls,'response_tokens':output,'argument_tokens':input_tokens}

def main(args):
    store=MemoryStore();rows=[];sources=[];seen=set();expansions={}
    for number,path in enumerate(args.thread,1):
        source=path.read_text();digest=hashlib.sha256(source.encode()).hexdigest()
        if digest in seen:raise ValueError('Duplicate thread export')
        seen.add(digest);sources.append({'thread':number,'sha256':digest})
        for call in parse_thread(source):
            if not call['name'].startswith('onshape_native.'):continue
            tool=call['name'].split('.')[-1];inputs=call['arguments'] or {};body=call['response']
            try:old=json.loads(body)
            except (ValueError,TypeError):old=None
            new=None;provenance='error or non-JSON response'
            if isinstance(old,dict) and not call['error']:
                new,provenance=replay(tool,inputs,old,args.cache,store)
            before=tokens(body) if body is not None else None
            after=tokens(new) if new is not None else before
            cost={'calls':0,'response_tokens':0,'argument_tokens':0}
            # Model additional demand only for intentionally deferred sections.
            details=(new or {}).get('details',{})
            pointer=details.get('pointer')
            handle=details.get('artifact') or (new or {}).get('artifact') or (new or {}).get('snapshot')
            if new is not None and pointer is not None and handle in store.values:
                key=(handle,pointer)
                if key not in expansions:expansions[key]=expansion_cost(store,handle,pointer)
                cost=expansions[key]
            rows.append({'thread':number,'call':call['ordinal'],'source_line':call['line'],'tool':tool,
                         'variant':variant(call['name'],inputs),'provenance':provenance,'replayed':new is not None,
                         'before':before,'after':after,'saved':before-after if before is not None else 0,
                         'argument_tokens':tokens(inputs),'detail_calls':cost['calls'],
                         'detail_response_tokens':cost['response_tokens'],'detail_argument_tokens':cost['argument_tokens']})
    groups=collections.defaultdict(list)
    for row in rows:groups[row['tool']].append(row)
    tools=[]
    for tool,group in groups.items():
        old=sum(r['before'] or 0 for r in group);new=sum(r['after'] or 0 for r in group)
        tools.append({'tool':tool,'calls':len(group),'replayed':sum(r['replayed'] for r in group),
                      'before':old,'after':new,'saved':old-new,'percent':round(100*(old-new)/old,2) if old else 0})
    before=sum(t['before'] for t in tools);after=sum(t['after'] for t in tools)
    eligible=sum(r['detail_calls']>0 for r in rows)
    detail={k:sum(r[k] for r in rows) for k in ('detail_calls','detail_response_tokens','detail_argument_tokens')}
    arguments=sum(r['argument_tokens'] for r in rows)
    scenarios=[{'expansion_percent':p,'expected_total_calls':round(len(rows)+p/100*detail['detail_calls'],1),
                'response_tokens':round(after+p/100*detail['detail_response_tokens']),
                'response_plus_argument_tokens':round(after+arguments+p/100*(detail['detail_response_tokens']+detail['detail_argument_tokens']))}
               for p in (0,10,25,50,100)]
    metrics={'tokenizer':'o200k_base','sources':sources,'formatter_sha256':{name:hashlib.sha256((ROOT/'onshape_native'/name).read_bytes()).hexdigest() for name in ('responses.py','store.py')},'totals':{'calls':len(rows),'before':before,'after':after,
             'saved':before-after,'percent':round(100*(before-after)/before,2),'replayed_calls':sum(r['replayed'] for r in rows),
             'eligible_detail_responses':eligible,'original_argument_tokens':arguments,'missing_responses':sum(r['before'] is None for r in rows),**detail},
             'coverage':dict(collections.Counter(r['provenance'] for r in rows)),
             'tools':sorted(tools,key=lambda r:r['saved'],reverse=True),'scenarios':scenarios,
             'method':'Offline replay through production respond/tree_page/Store.page; original frequencies retained. Missing raw payloads, errors and out-of-scope tools carried forward unchanged. Additional detail demand is a uniform hypothetical rate; entire advertised sections retrieved with pagination, not a single-page approximation. Original artifact_page calls retained. Text tokens only; not provider billing or an agent task rerun.'}
    previous=ROOT/'docs/token-audit/compression-v1/metrics.json'
    if previous.exists():
        prior=json.loads(previous.read_text())['totals']['after']
        metrics['previous_implementation']={'response_tokens':prior,'additional_saved':prior-after,'additional_reduction_percent':round(100*(prior-after)/prior,2)}
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    (out/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    for name,data in [('calls',rows),('tools',metrics['tools']),('scenarios',scenarios)]:
        with (out/f'{name}.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    charts(metrics,out);report(metrics,out)
    print(json.dumps({'output':str(out),'totals':metrics['totals'],'coverage':metrics['coverage']},indent=2))

def charts(m,out):
    plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,'font.size':11})
    def save(fig,name):
        fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=170,facecolor='white');fig.savefig(out/(name+'.svg'),facecolor='white');plt.close(fig)
    t=m['totals'];fig,ax=plt.subplots(figsize=(10,5))
    bars=ax.barh(['Recorded responses','Production-format replay'],[t['before'],t['after']],color=['#64748b','#0d9488'])
    ax.bar_label(bars,fmt='{:,.0f}',padding=8);ax.set_xlim(0,max(t['before'],t['after'])*1.18);ax.invert_yaxis()
    ax.set_xlabel('Response text tokens · o200k_base');ax.set_title(f"{t['percent']:.1f}% less initial response text on this trace\nSame {t['calls']} calls; extra detail retrieval excluded",loc='left');save(fig,'01-overall')
    rows=sorted(m['tools'],key=lambda r:r['before'],reverse=True)[:12]
    fig,ax=plt.subplots(figsize=(12,7));y=list(range(len(rows)))
    ax.barh([v-.18 for v in y],[r['before'] for r in rows],height=.36,label='Recorded',color='#64748b')
    ax.barh([v+.18 for v in y],[r['after'] for r in rows],height=.36,label='Replayed / carried forward',color='#0d9488')
    ax.set_yticks(y,[f"{r['tool']} ({r['calls']} calls)" for r in rows]);ax.invert_yaxis();ax.legend();ax.set_xlabel('Total response text tokens');ax.set_title('Frequency-weighted cost by tool\nIncludes increases from more informative pages',loc='left');save(fig,'02-tools')
    fig,axes=plt.subplots(1,2,figsize=(13,5));s=m['scenarios'];x=[r['expansion_percent'] for r in s]
    axes[0].plot(x,[r['response_tokens'] for r in s],marker='o',color='#0d9488',label='With additional expansion')
    axes[0].axhline(t['before'],color='#64748b',linestyle='--',label='Recorded response tokens');axes[0].set_ylabel('Response text tokens');axes[0].legend()
    axes[1].plot(x,[r['expected_total_calls'] for r in s],marker='o',color='#2563eb');axes[1].axhline(t['calls'],color='#64748b',linestyle='--');axes[1].set_ylabel('Expected total tool calls')
    for ax in axes:ax.set_xlabel('Summaries whose advertised section is fully expanded (%)');ax.grid(alpha=.15)
    fig.suptitle('Sensitivity, not observed behavior: full detail can cost more\nEvery required child/page call is counted; original calls are retained',fontsize=13);save(fig,'03-detail-demand')

def report(m,out):
    t=m['totals'];table='\n'.join(f"| `{r['tool']}` | {r['calls']} | {r['replayed']} | {r['before']:,} | {r['after']:,} | {r['saved']:+,} | {r['percent']:+.1f}% |" for r in m['tools'])
    scenarios='\n'.join(f"| {r['expansion_percent']}% | {r['expected_total_calls']:,.1f} | {r['response_tokens']:,} | {r['response_plus_argument_tokens']:,} |" for r in m['scenarios'])
    coverage='\n'.join(f'- {k}: {v} calls' for k,v in m['coverage'].items())
    prior=m.get('previous_implementation')
    comparison=(f"Previous implementation: {prior['response_tokens']:,} tokens → {t['after']:,}, an additional {prior['additional_saved']:,} tokens saved ({prior['additional_reduction_percent']}%). The archived first-pass report is in ../compression-v1/." if prior else '')
    text=f'''# Implemented compression: updated statistics

**Initial response text: {t['before']:,} → {t['after']:,} tokens ({t['percent']:.2f}% reduction).**

{comparison}

**Tool calls: {t['calls']} → {t['calls']} (0% reduction).** This change compresses returns; it does not eliminate calls. Additional expansion may increase call count. All 35 MCP tools remain available.

![Overall comparison](01-overall.png)

## What was measured

Replayed recoverable original responses from the two supplied threads through the **actual implemented formatting functions**, with the same original arguments and call frequencies. No CAD requests or edits were made. {t['replayed_calls']} of {t['calls']} calls could be replayed in scope; the remaining responses were carried forward unchanged, not assigned invented savings. Any missing raw payloads would be carried forward unchanged. This is an offline response-format replay, not a new end-to-end agent run or proof that task outcomes remain identical.

Tokenizer: `o200k_base`. Text only; excludes image tokens, system/tool-definition overhead, provider billing and hidden metadata. Original compact argument tokens: {t['original_argument_tokens']:,}; they are unchanged in the main comparison. Missing exported Native responses: {t['missing_responses']}.

{coverage}

Cached inputs are SHA-256 checked against their handles. Where a cache file is missing, a complete exported value is used only if its hash matches. Discovery responses can be reformatted directly. Unsupported/unchanged tools and explicit errors retain their historical text. Updated paging is included for replayable `artifact_page` calls. New camera/display commands with no recorded calls receive no assumed savings. Smaller default read pages defer more data; this replay does not estimate the extra calls required to consume those new continuations. The sensitivity table covers explicitly advertised deferred sections only, not all newly deferred read pages. Current hierarchy query filters are not retroactively added to old agent requests.

## Frequency-weighted results

Positive savings means fewer tokens; negative means more. More informative assembly fallbacks and larger usable page prefixes can **increase** initial output; these increases are included.

| Tool | Calls | Replayed | Before | After | Tokens saved | Reduction |
|---|---:|---:|---:|---:|---:|---:|
{table}

![Per-tool comparison](02-tools.png)

## What if the agent needs the omitted details?

There are {t['eligible_detail_responses']} replayed replies with an advertised deferred section. The following scenarios assume the same fraction of these replies needs its **entire advertised section**, using only `artifact_page`. Every continuation and narrower child call is counted. Feature replies expand `/feature`; schemas expand their full operation report (including deferred prose and `/responses`); discovery expands its full report; hierarchy expands `/rows`. This can overfetch compared with an agent choosing one field/row. Existing detail calls remain in the original trace, so additional expansion can also double count demand already satisfied there. These are sensitivity scenarios, not measured user behavior. Fractional call totals are statistical expectations.

| Additional full-section demand | Expected calls | Response tokens | Responses + arguments |
|---|---:|---:|---:|
{scenarios}

![Expansion sensitivity](03-detail-demand.png)

Use the initial-response reduction as the verified formatting result on this sample, not a guaranteed total-workflow saving. A future live trace should record how often summaries trigger `artifact_page`, whether tasks finish, and total tokens including retrieval. The older audit's aggressive projection is not the implemented result.

## Reproduce

```sh
uv run --project . --with-requirements scripts/audit-requirements.txt \\
  python scripts/compression_audit.py --thread /path/to/design.txt --thread /path/to/cameras.txt
```

Outputs: [per-call CSV](calls.csv), [per-tool CSV](tools.csv), [scenario CSV](scenarios.csv), [full metrics](metrics.json). No raw CAD payloads, document identifiers, or transcript text are included in these reports. The prior [frequency audit](../usage/README.md) is preserved.
'''
    (out/'README.md').write_text(text)
    chart_html=''.join(f'<img src="{name}.svg" alt="{label}">' for name,label in [('01-overall','Overall response comparison'),('02-tools','Cost by tool'),('03-detail-demand','Expansion demand sensitivity')])
    (out/'index.html').write_text(f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Onshape compression results</title><style>body{{font:17px system-ui;margin:40px auto;padding:0 24px;max-width:1150px;color:#173042;background:#f8fafc}}h1{{font-size:36px}}.stats{{display:flex;gap:35px;flex-wrap:wrap;padding:24px;background:white;border-radius:14px}}strong{{font-size:30px}}img{{width:100%;background:white;margin:20px 0;border-radius:12px}}p{{line-height:1.6}}a{{color:#087e73}}</style><h1>Implemented compression results</h1><div class="stats"><div><strong>{t['percent']:.1f}%</strong><br>less initial response text</div><div><strong>{t['saved']:,}</strong><br>tokens saved in replay</div><div><strong>{t['calls']} → {t['calls']}</strong><br>original tool calls unchanged</div></div><p>Two supplied threads · {t['replayed_calls']} calls replayed through production formatting · remaining calls carried forward · o200k_base text tokens. Offline replay, not an agent task rerun. Additional detail demand is hypothetical and can erase savings.</p><p><a href="README.md">Method and complete tables</a> · <a href="tools.csv">Tool CSV</a> · <a href="calls.csv">Call CSV</a> · <a href="metrics.json">Metrics JSON</a></p>{chart_html}</html>''')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--thread',type=Path,action='append',required=True)
    p.add_argument('--cache',type=Path,default=ROOT/'.runtime/artifacts')
    p.add_argument('--output',type=Path,default=ROOT/'docs/token-audit/compression')
    main(p.parse_args())
