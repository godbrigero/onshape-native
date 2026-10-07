#!/usr/bin/env python3
"""Add observed thread frequencies to the token audit. Never executes transcript code."""
import argparse,collections,csv,difflib,hashlib,html,json,re,statistics
from pathlib import Path
from usage_audit import parse_thread,variant,browser_intent
from token_audit import tokens,lean,ROOT
import matplotlib.pyplot as plt


def main(args):
    sources=[p.read_text() for p in args.thread]
    hashes=[hashlib.sha256(s.encode()).hexdigest() for s in sources]
    if len(set(hashes))!=len(hashes):raise ValueError('Duplicate export supplied; refusing to double count it.')
    calls=[];source_records=[];fingerprints=[]
    for i,source in enumerate(sources,1):
        parsed=parse_thread(source);thread=f'thread-{i}'
        source_records.append({'thread':thread,'sha256':hashes[i-1],'bytes':len(source.encode()),'export_line_count':len(source.splitlines()),'skill_versions_mentioned':sorted(set(re.findall(r'onshape-native/(\d+\.\d+\.\d+)/skills',source)))})
        fingerprints.append([hashlib.sha256(json.dumps([c['name'],c['arguments'],c['response']],sort_keys=True).encode()).hexdigest() for c in parsed])
        for c in parsed:c.update(thread=thread,thread_call=c['ordinal'],ordinal=len(calls)+1);calls.append(c)
    source='\n'.join(sources)
    overlap=[]
    for i in range(len(fingerprints)):
        for j in range(i+1,len(fingerprints)):
            a,b=fingerprints[i],fingerprints[j]
            overlap.append({'thread_a':i+1,'thread_b':j+1,'shared_exact_payload_fingerprints':len(set(a)&set(b)),'longest_shared_contiguous_run':max(block.size for block in difflib.SequenceMatcher(None,a,b,autojunk=False).get_matching_blocks()),'deduplicated_calls':0})
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((ROOT/'docs/token-audit/metrics.json').read_text())
    current={r['tool']:r for r in baseline['coverage']}
    cache=ROOT/'.runtime/artifacts';cached={p.name for p in cache.glob('*.json')}
    rows=[];variants=collections.defaultdict(list);repeated=collections.Counter();transitions=collections.Counter()
    referenced=set();field_usage=collections.Counter();groups=collections.defaultdict(list)
    shell_cache_reads=sum('.runtime/artifacts' in line for line in source.splitlines())
    for c in calls:
        native=c['name'].startswith('onshape_native.');tool=c['name'].split('.')[-1] if native else c['name']
        surface='native' if native else 'official-api' if c['name'].startswith('onshape_cad.') else 'browser' if c['name']=='cua_repl.js' else 'other'
        body=c['response'];parsed=None
        if body is not None:
            try:parsed=json.loads(body)
            except ValueError:pass
        args_obj=c['arguments'];variant_name=browser_intent(args_obj) if surface=='browser' else variant(c['name'],args_obj)
        fallback=isinstance(parsed,dict) and bool(parsed.get('needs_narrower_pointer'))
        response_tokens=tokens(body) if body is not None else None
        projected=lean(tool,parsed) if isinstance(parsed,dict) and native else None
        # A detail projection for schema discovery; preserves types, required fields,
        # enum/default constraints, routing and references. Long prose stays on demand.
        if tool=='api_catalog' and isinstance(parsed,dict) and args_obj.get('schema'):
            def schema_outline(obj):
                if isinstance(obj,list):return [schema_outline(x) for x in obj]
                if not isinstance(obj,dict):return obj
                return {k:schema_outline(v) for k,v in obj.items() if k not in ('description','summary','title','example','examples','externalDocs')}
            projected=schema_outline(parsed)
        # Artifact paging of hierarchy rows needs the same sparse hierarchy view.
        if tool=='artifact_page' and isinstance(parsed,dict) and isinstance(parsed.get('data'),list) and parsed['data'] and all(isinstance(r,dict) and 'parent_id' in r for r in parsed['data']):
            projected=lean('element_tree',parsed)
        if tool=='api_write' and isinstance(parsed,dict) and parsed.get('artifact'):
            data=parsed.get('data',{})
            if isinstance(data,dict) and isinstance(data.get('feature'),dict) and isinstance(data.get('featureState'),dict) and data['featureState'].get('featureStatus')=='OK' and not data.get('microversionSkew'):
                projected=dict(lean(tool,parsed));projected['data']=dict(data)
                projected['data']['feature']={k:v for k,v in data['feature'].items() if k in ('featureId','featureType','name')}
                projected['feature_details']={'artifact':parsed['artifact'],'pointer':'/feature'}
        proposed_tokens=tokens(projected) if projected is not None and not c['error'] and not fallback else response_tokens
        r={'call':c['ordinal'],'thread':c['thread'],'thread_call':c['thread_call'],'source_line':c['line'],'tool':tool,'surface':surface,'variant':variant_name,
           'response_tokens':response_tokens,'argument_tokens':tokens(args_obj),'argument_rendered_tokens':tokens(c['request_text']),
           'projected_response_tokens':proposed_tokens,'explicit_error':c['error'],'pointer_fallback':fallback,'image_output':c['image_output'],
           'empty_response':body=='','response_present':body is not None}
        rows.append(r);groups[tool].append(r);variants[(tool,variant_name)].append(r)
        if native:
            key=hashlib.sha256(json.dumps({'thread':c['thread'],'tool':tool,'args':args_obj},sort_keys=True).encode()).hexdigest();repeated[(tool,key)]+=1
            for field in args_obj:field_usage[(tool,field)]+=1
        for text in [c['request_text'],body]:
            referenced.update(re.findall(r'\b[a-f0-9]{64}\.json\b',text or ''))
    native_rows=[r for r in rows if r['surface']=='native'];browser_rows=[r for r in rows if r['surface']=='browser'];official_rows=[r for r in rows if r['surface']=='official-api']
    for a,b in zip(native_rows,native_rows[1:]):
        if a['thread']==b['thread']:transitions[(a['tool'],b['tool'])]+=1
    def aggregate(tool,group):
        values=[r['response_tokens'] for r in group if r['response_tokens'] is not None]
        return {'tool':tool,'calls':len(group),'share_native_calls_percent':round(100*len(group)/len(native_rows),2) if tool in current else None,
                'responses_measured':len(values),'missing_responses':len(group)-len(values),'response_tokens':sum(values),'mean_response_tokens':round(statistics.mean(values),1) if values else None,
                'argument_tokens':sum(r['argument_tokens'] for r in group),'projected_response_tokens':sum(r['projected_response_tokens'] or 0 for r in group),
                'explicit_errors':sum(r['explicit_error'] for r in group),'pointer_fallbacks':sum(r['pointer_fallback'] for r in group),'images':sum(r['image_output'] for r in group)}
    alltools=[]
    for tool in sorted(set(current)|{r['tool'] for r in native_rows}):
        item=aggregate(tool,groups[tool]);item['definition_tokens']=current.get(tool,{}).get('tokens');item['observed_text_savings']=item['response_tokens']-item['projected_response_tokens'];alltools.append(item)
    op_rows=[{'variant':v,**aggregate(t,g)} for (t,v),g in variants.items()]
    duplicate_rows=[{'tool':t,'identical_request_groups':sum(1 for (tool,_),n in repeated.items() if tool==t and n>1),'repeated_after_first':sum(n-1 for (tool,_),n in repeated.items() if tool==t)} for t in sorted({t for t,_ in repeated})]
    schema_calls=[c for c in calls if c['name']=='onshape_native.api_catalog' and c['arguments'].get('schema')]
    schema_distinct=len({c['arguments']['schema'] for c in schema_calls})
    schema_pairs=collections.Counter((c['thread'],c['arguments']['schema']) for c in schema_calls)
    total=sum(r['response_tokens'] or 0 for r in native_rows)
    top=sorted(alltools,key=lambda x:x['response_tokens'],reverse=True)
    rare=[r['tool'] for r in alltools if r['calls']==0]
    initial_walk=[]
    # Count the opening document-navigation sequence, ending at the first inspection.
    for r in native_rows:
        if r['tool']=='inspect_model':break
        if r['tool'] in ('document_tree','artifact_page'):initial_walk.append(r)
    metrics={'source':{'sha256':hashlib.sha256(source.encode()).hexdigest(),'bytes':len(source.encode()),'thread_count':1,'export_line_count':len(source.splitlines()),'skill_versions_mentioned':sorted(set(re.findall(r'onshape-native/(\d+\.\d+\.\d+)/skills',source)))},
       'method':{'primary_tokenizer':'o200k_base','frequency':'One explicit MCP tool-call record = one call, including errors/retries. Mentions and code examples are excluded. Repeated calls are retained. Official API calls are separate from Native calls.','response_measure':'Visible exported text only; missing responses and image tokens are excluded, not assigned zero costs. Arguments measured as compact JSON separately.','generalization':'Selected task threads, not a production usage distribution. Old skill/version and capability availability confound zero counts.','cache_frequency':'Cache artifacts deduplicate payloads, span unrelated research runs, and are not invocation logs. Never added to call frequencies.','counterfactual':'Same recorded responses, task-specific projections only; no assumed reduction in call count, no performance claim. Missing responses remain unknown.'},
       'totals':{'mcp_calls':len(calls),'native_calls':len(native_rows),'browser_calls':len(browser_rows),'official_api_calls':len(official_rows),'official_api_response_text_tokens':sum(r['response_tokens'] or 0 for r in official_rows),'native_response_text_tokens':total,'native_argument_tokens':sum(r['argument_tokens'] for r in native_rows),'browser_response_text_tokens':sum(r['response_tokens'] or 0 for r in browser_rows),'browser_argument_tokens':sum(r['argument_tokens'] for r in browser_rows),'missing_native_responses':sum(not r['response_present'] for r in native_rows),'missing_browser_responses':sum(not r['response_present'] for r in browser_rows),'native_explicit_errors':sum(r['explicit_error'] for r in native_rows),'native_pointer_fallbacks':sum(r['pointer_fallback'] for r in native_rows),'projected_native_response_tokens':sum(r['projected_response_tokens'] or 0 for r in native_rows)},
       'cache':{'json_artifacts':len(cached),'unique_artifacts_referenced_in_export':len(referenced),'referenced_artifacts_present':len(referenced&cached),'shell_lines_referencing_artifact_cache':shell_cache_reads,'legacy_onshape_cache_files':len(list((ROOT.parent/'.onshape-cache').glob('*'))),'persistent_invocation_log_found':False,'bridge_access_logging':False},
       'tools':alltools,'calls':rows,'variants':op_rows,'argument_fields':[{'tool':t,'field':f,'calls':n} for (t,f),n in sorted(field_usage.items())],
       'repeated_requests':duplicate_rows,'transitions':[{'from':a,'to':b,'count':n} for (a,b),n in transitions.most_common()],
       'browser_intents':[{'intent':v,'calls':len(g),'text_tokens':sum(r['response_tokens'] or 0 for r in g)} for (t,v),g in variants.items() if t=='cua_repl.js'],
       'findings':{'schema_requests':len(schema_calls),'distinct_schema_requests':schema_distinct,'opening_navigation_calls':len(initial_walk),'opening_navigation_response_tokens':sum(r['response_tokens'] or 0 for r in initial_walk),'top3_response_share_percent':round(sum(r['response_tokens'] for r in top[:3])/total*100,1),'unobserved_tools':rare}}
    metrics['source']={'thread_count':len(sources),'exports':source_records,'overlap':overlap}
    metrics['thread_tools']=[{'thread':thread,**aggregate(tool,[r for r in rows if r['thread']==thread and r['tool']==tool])} for thread in [s['thread'] for s in source_records] for tool in sorted(current)]
    metrics['thread_summary']=[{'thread':s['thread'],'native_calls':sum(r['thread']==s['thread'] for r in native_rows),'native_response_tokens':sum(r['response_tokens'] or 0 for r in native_rows if r['thread']==s['thread']),'official_api_calls':sum(r['thread']==s['thread'] for r in official_rows),'browser_calls':sum(r['thread']==s['thread'] for r in browser_rows)} for s in source_records]
    thread_totals={s['thread']:s['native_calls'] for s in metrics['thread_summary']}
    for r in metrics['thread_tools']:r['share_native_calls_percent']=round(100*r['calls']/thread_totals[r['thread']],2) if thread_totals[r['thread']] else None
    metrics['official_tools']=[aggregate(t,g) for t,g in groups.items() if t.startswith('onshape_cad.')]
    metrics['findings']['schema_repeats_within_thread']=sum(n-1 for n in schema_pairs.values())
    (root/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    for name,items in [('tools',alltools),('calls',rows),('variants',op_rows),('argument-fields',metrics['argument_fields']),('transitions',metrics['transitions']),('repeated-requests',duplicate_rows),('thread-tools',metrics['thread_tools']),('thread-summary',metrics['thread_summary']),('official-api-tools',metrics['official_tools'])]:
        if not items:continue
        with (root/(name+'.csv')).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=items[0].keys());writer.writeheader();writer.writerows(items)
    draw(metrics,root);report(metrics,root)
    print(json.dumps({'totals':metrics['totals'],'cache':metrics['cache'],'findings':metrics['findings'],'top_tools':top[:7]},indent=2))


def draw(m,out):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'#f8fafc','axes.facecolor':'#f8fafc','savefig.facecolor':'#f8fafc'})
    def save(fig,name):fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=160,bbox_inches='tight');fig.savefig(out/(name+'.svg'),bbox_inches='tight');plt.close(fig)
    rows=sorted([r for r in m['tools'] if r['calls']],key=lambda r:r['calls'])
    fig,ax=plt.subplots(figsize=(12,8));bars=ax.barh([r['tool'] for r in rows],[r['calls'] for r in rows],color='#2563eb');ax.bar_label(bars,padding=4);ax.set_xlim(0,max(r['calls'] for r in rows)*1.12);ax.set_xlabel('Recorded calls, including errors and retries');ax.set_title(f"Actual frequency: {m['totals']['native_calls']} Onshape Native calls across {m['source']['thread_count']} threads\nBrowser and official API calls stay separate; zero use is not lack of need",loc='left');save(fig,'01-frequency')
    rows=sorted([r for r in m['tools'] if r['calls']],key=lambda r:r['response_tokens'],reverse=True)
    fig,ax=plt.subplots(figsize=(14,7));ax.bar(range(len(rows)),[r['response_tokens'] for r in rows],color='#0d9488');ax.set_xticks(range(len(rows)),[r['tool'] for r in rows],rotation=55,ha='right');ax.set_ylabel('Measured response text tokens');ax.set_title('Frequency × response size: where the thread actually spent context',loc='left');other=ax.twinx();cumulative=[];s=0
    for r in rows:s+=r['response_tokens'];cumulative.append(100*s/m['totals']['native_response_text_tokens'])
    other.plot(range(len(rows)),cumulative,color='#ea580c',marker='o');other.set_ylabel('Cumulative share (%)');other.set_ylim(0,105);save(fig,'02-weighted-cost')
    fig,ax=plt.subplots(figsize=(12,7))
    for r in rows:
        ax.scatter(r['calls'],r['mean_response_tokens'] or 1,s=max(25,r['response_tokens']/20),alpha=.65,color='#2563eb')
    for i,r in enumerate(rows[:8]):ax.annotate(r['tool'],(r['calls'],r['mean_response_tokens']),xytext=(6,8 if i%2 else -13),textcoords='offset points',fontsize=9)
    ax.set_yscale('log');ax.set_xlabel('Observed calls');ax.set_ylabel('Mean response text tokens (log scale)');ax.set_title('Prioritize frequent, expensive returns\nBubble area represents total recorded response text',loc='left');ax.grid(alpha=.15);save(fig,'03-frequency-size')
    rows=sorted([r for r in m['tools'] if r['observed_text_savings']>0],key=lambda r:r['observed_text_savings'])
    fig,ax=plt.subplots(figsize=(12,7));ax.barh([r['tool'] for r in rows],[r['response_tokens'] for r in rows],color='#2563eb',label='Recorded text')
    ax.barh([r['tool'] for r in rows],[r['projected_response_tokens'] for r in rows],color='#0d9488',label='Proposed default summaries')
    ax.set_xlabel('Tokens across this thread, retaining observed call counts');ax.legend();ax.set_title('Frequency-weighted potential: preserve full detail on demand\nThis projection does not assume fewer calls or include extra detail-fetch costs',loc='left');save(fig,'04-weighted-savings')
    fig,axes=plt.subplots(1,2,figsize=(14,6));native=[r for r in m['calls'] if r['surface']=='native'];browser=[r for r in m['calls'] if r['surface']=='browser']
    for group,label,color in [(native,'Onshape Native','#2563eb'),(browser,'Browser','#d97706')]:
        x=[];y=[];v=0
        for r in group:v+=r['response_tokens'] or 0;x.append(r['call']);y.append(v)
        axes[0].plot(x,y,label=label,color=color)
    axes[0].set_xlabel('MCP call ordinal in export');axes[0].set_ylabel('Cumulative visible response text tokens');axes[0].legend();axes[0].set_title('How the workflow shifted to the browser',loc='left')
    b=sorted(m['browser_intents'],key=lambda r:r['calls']);axes[1].barh([r['intent'] for r in b],[r['calls'] for r in b],color='#d97706');axes[1].set_title('Browser intent inferred from call titles',loc='left');axes[1].set_xlabel('Calls (exclusive heuristic categories)');save(fig,'05-browser-demand')
    tools=[r['tool'] for r in sorted(m['tools'],key=lambda r:r['calls'],reverse=True)[:12]]
    fig,ax=plt.subplots(figsize=(12,7));threads=m['thread_summary'];height=.75/max(1,len(threads))
    for i,thread in enumerate(threads):
        by={r['tool']:r for r in m['thread_tools'] if r['thread']==thread['thread']}
        values=[100*by[t]['calls']/thread['native_calls'] for t in tools]
        ax.barh([j+i*height for j in range(len(tools))],values,height=height,label=f"{thread['thread']} ({thread['native_calls']} Native calls)")
    ax.set_yticks([j+(len(threads)-1)*height/2 for j in range(len(tools))],tools);ax.invert_yaxis();ax.set_xlabel('Share of Native calls within each thread (%)');ax.legend();ax.set_title('Workloads differ: normalize before generalizing demand',loc='left');save(fig,'06-thread-comparison')


def report(m,out):
    totals=m['totals'];findings=m['findings'];cache=m['cache'];ranked=sorted(m['tools'],key=lambda r:r['response_tokens'],reverse=True)
    table='\n'.join(f"| `{r['tool']}` | {r['calls']} | {r['mean_response_tokens'] if r['mean_response_tokens'] is not None else '—'} | {r['response_tokens']:,} | {r['explicit_errors']} / {r['pointer_fallbacks']} |" for r in ranked)
    variant_table='\n'.join(f"| `{r['tool']}` | `{r['variant']}` | {r['calls']} | {r['response_tokens']:,} |" for r in sorted([v for v in m['variants'] if '.' not in v['tool']],key=lambda r:r['response_tokens'],reverse=True)[:20])
    thread_table='\n'.join(f"| {r['thread']} | {r['native_calls']} | {r['native_response_tokens']:,} | {r['official_api_calls']} | {r['browser_calls']} |" for r in m['thread_summary'])
    versions=sorted({v for s in m['source']['exports'] for v in s['skill_versions_mentioned']})
    by_variant={(r['tool'],r['variant']):r for r in m['variants']}
    def op(tool,name,key):return by_variant.get((tool,name),{}).get(key,0)
    feature_echo_cost=sum(op('api_write',name,'response_tokens') for name in ['addFeature','updateFeature'])
    overlap_summary='; '.join(f"threads {p['thread_a']}/{p['thread_b']}: {p['shared_exact_payload_fingerprints']} shared fingerprints, longest contiguous match {p['longest_shared_contiguous_run']} call(s)" for p in m['source']['overlap']) or 'Only one export; no cross-export comparison.'
    nav=findings['opening_navigation_calls'];navcost=findings['opening_navigation_response_tokens'];saving=totals['native_response_text_tokens']-totals['projected_native_response_tokens']
    text=f'''# Frequency-weighted Onshape Native audit

This extends the [size audit](../README.md) with **observed command frequency** from {m['source']['thread_count']} supplied threads. Counted **{totals['native_calls']} Onshape Native calls, {totals['official_api_calls']} official-API calls and {totals['browser_calls']} browser calls**, including failures and repeated requests. Official API (`onshape_cad`) usage is **not merged into Native frequencies**. All 35 current Native tools appear in the inventory, including zero-observation entries.

Thread 1 is the design/connector workflow. Thread 2 is the camera-placement workflow, which also includes substantial official-API work. The combined count is call-weighted; the longer second thread has more influence. Compare normalized per-thread frequencies before treating these as general agent behavior.

| Thread | Native calls | Native response tokens | Official API calls | Browser calls |
|---|---:|---:|---:|---:|
{thread_table}

![Per-thread usage comparison](06-thread-comparison.png)

## What the numbers change

The top three tools by recorded response cost—**api_write, api_catalog, api_read** in this two-thread study—account for **{findings['top3_response_share_percent']}%** of the measured Native output. Optimize those first, rather than ranking only by the size of one reply. The size-only 48-call scenario in the previous audit is illustrative; this report uses the attached threads' actual counts and returned text.

Concrete priorities from the observed operations:

- **Compact successful feature-write acknowledgements.** `addFeature` and `updateFeature` produced **{feature_echo_cost:,} response tokens** across {op('api_write','addFeature','calls')+op('api_write','updateFeature','calls')} calls, mostly echoing full feature definitions. Keep feature IDs, status, revision/skew and an exact full-definition pointer immediately available; return full parameters only on demand. Preserve rich failure responses.
- **Assembly summaries/projections instead of unusable default pages.** `getAssemblyDefinition` was called **{op('api_read','getAssemblyDefinition','calls')} times**; **{op('api_read','getAssemblyDefinition','pointer_fallbacks')} returned narrower-pointer hints**. Many of these reads can still be necessary freshness checks. Change their return format to a useful summary plus valid pointers or requested instance/mate fields, not a cache that silently skips verification.
- **Concise schemas with optional explanation.** There are {findings['schema_requests']} schema calls and **{findings['schema_repeats_within_thread']} repeats after the first within a thread**. Key reusable schema handles by schema/build version. Keep required fields, defaults, enums, units and constraint explanations; make long background prose/examples an explicit detail fetch. The numeric projection strips prose as a sizing experiment, so a production outline must selectively restore descriptions that encode otherwise implicit constraints.
- **Requested mass fields.** `getPartStudioMassProperties` accounts for **{op('api_read','getPartStudioMassProperties','response_tokens'):,} tokens in {op('api_read','getPartStudioMassProperties','calls')} calls**. Weight-only requests should not automatically include every inertia tensor, but simulation tasks must retain one-step access to mass, centroid, axes and inertia.
- **Keep custom evaluation discoverable.** **{op('evaluate','custom','calls')} of {sum(v['calls'] for v in m['variants'] if v['tool']=='evaluate')} evaluation calls used custom FeatureScript**. It is not a rare escape hatch in these tasks. Keep compact measurement/select presets nearby, with custom script support available explicitly.

There were **{totals['native_response_text_tokens']:,} visible Native response tokens** and **{totals['native_argument_tokens']:,} compact argument tokens**, plus **{totals['browser_response_text_tokens']:,} visible browser response tokens**. These are text-tokenizer measurements, not billed totals. Images, unseen tool metadata and missing/truncated exported content are not recoverable as token counts. Missing responses: Native {totals['missing_native_responses']}, browser {totals['missing_browser_responses']}. Explicit Native errors: {totals['native_explicit_errors']}; narrower-pointer replies: {totals['native_pointer_fallbacks']}.

![Observed call frequency](01-frequency.png)

![Weighted context cost](02-weighted-cost.png)

| Tool | Calls | Mean response tokens | Total response tokens | Errors / pointer fallback |
|---|---:|---:|---:|---:|
{table}

## How the tools were used

The opening document navigation consumed **{nav} document-tree/artifact-page calls and {navcost:,} response tokens** before the first Part Studio inspection. The agent reduced page sizes after failures, attempted an incorrect `/elements` pointer, discovered `/rows`, then walked small pages to find a target. These calls are real usage, but not all represent desired functionality: a precise element lookup could replace much of the discovery detour without removing browsing.

Schema discovery included **{findings['schema_requests']} schema requests covering {findings['distinct_schema_requests']} distinct schema names**. Repeated exact requests are reported separately in `repeated-requests.csv`; repetition alone does not prove waste, since refreshes and error recovery may be necessary. The full operation breakdown below distinguishes generic tool wrappers from actual actions. FeatureScript custom evaluation, feature edits, assembly operations and topology inspection remain available even when their full schemas are not part of the default response.

| Tool | Requested operation / variant | Calls | Response tokens |
|---|---|---:|---:|
{variant_table}

![Frequency and reply size](03-frequency-size.png)

## Cache evidence and counting rules

- Found **{cache['json_artifacts']} JSON artifacts** in `onshape-native/.runtime/artifacts`; **{cache['referenced_artifacts_present']} of {cache['unique_artifacts_referenced_in_export']} distinct artifact handles** referenced in the export exist there. They support provenance and the previous response-size study.
- The legacy `.onshape-cache` contains **{cache['legacy_onshape_cache_files']} files**. Pytest caches contain test state, not agent command usage. Runtime research/validation JSON is not a chronological call ledger.
- No persistent invocation log was found in the project. The bridge disables HTTP access logging. Artifact files are content-addressed: repeated calls can yield one file, and one call can yield several files. **Do not add artifact counts to transcript frequencies.**
- The export also has **{cache['shell_lines_referencing_artifact_cache']} shell-code lines referencing the artifact cache**. Shell helpers read/filter geometry locally, so Native call counts alone do not describe all agent work. These are not falsely counted as MCP calls; shell outputs are not comprehensively available in the export.
- The parser counts explicit `MCP tool call` records outside fenced examples, preserves retries and excludes prose mentions. It records source line numbers for traceability, but publishes no raw arguments, model IDs, document names, URLs, response bodies or credentials. Source SHA-256 is in `metrics.json`.
- These are **{m['source']['thread_count']} selected threads**, with older skill references ({', '.join(versions) or 'unknown'}). Their frequencies are neither fleet-wide demand nor a reason to remove an unobserved tool. Cache data and transcripts are kept separate to prevent double counting. Cross-export exact call-payload overlap: {overlap_summary}. Isolated matches are consistent with repeated standalone reads/schema discovery; they cannot prove event identity without call IDs. Duplicate whole exports are rejected. No events were dropped merely because their arguments/results matched.

## Browser work reveals demand missing from the Native counts

![Browser demand](05-browser-demand.png)

The browser phase inspected inherited connectors, changed marker visibility, exposed revolute controls and previewed lidar motion. Title-based categories are proxies and leave ambiguous calls separate; one browser call is not necessarily one future Native call. Camera framing and screenshots can occur inside multi-action browser calls even when the title emphasizes visibility.

`display_state`, `set_visibility`, `mate_animation`, `view_control` and `capture_viewport` therefore deserve a **task-triggered display/motion group**, despite zero direct calls in this older trace. Do not bury them merely because they were unavailable when this workflow ran.

## Preserve capability through progressive disclosure

1. **Default: compact browse and verify.** Keep target resolution, hierarchy lookup, inspection, bounded measurement results, exact IDs, revision/completeness/error state, and continuation handles immediately available. Add lookup by element ID/name/type and row projection so locating one tab does not require walking an entire document. Retain full traversal as an explicit option.
2. **On demand: full schemas and geometry detail.** A concise operation outline should carry method/path, required fields, constraints and references. Put long descriptions/examples, full optional parameter trees, transforms, normals, topology arrays and camera matrices behind `detail="full"`, `fields=[...]`, or a stable `details_ref`. Do not delete parameters or truncate data; full artifacts remain addressable. Small queries should expose available detail routes so the agent does not guess pointers.
3. **Mutation: compact verification, rich failure detail.** Return changed IDs, new revision/snapshot, verification and partial-completion status by default. Keep per-item full checks and raw native replies in artifacts. Failure diagnostics remain visible; “OK” alone is insufficient.
4. **Task-triggered tools: modeling, assembly, display/motion, advanced REST/native/UI.** Frequency can inform descriptions and suggested routes, but all tool families remain discoverable through search and exhaustive browsing. Native payload schemas, custom FeatureScript, uploads, exports and UI fallback should require one explicit detail step, not disappear. Client-side lazy schema loading is a separate optimization that needs Codex/Claude compatibility tests.
5. **Cache stable discovery, not mutable state.** Reuse operation schemas by schema/build version and feature templates by library/configuration key. Preserve explicit refresh. Snapshot paging may be local; fresh geometry/revision checks must still reach Onshape when needed.

The implementation order should be **feature-write acknowledgements → useful assembly projections → concise/versioned schema discovery → precise hierarchy lookup and compact rows → inspection/mass field selection**. Keep custom evaluation discoverable. The first thread alone made navigation look dominant; the second exposes repetitive assembly modeling. Use per-task routing rather than demoting an entire tool family from one aggregate ranking. The earlier camera-summary optimization remains valuable when display workflows trigger it.

## Frequency-weighted counterfactual

![Measured-frequency projections](04-weighted-savings.png)

Applying the previous task-specific summaries to the **actual recorded replies**, plus sparse hierarchy artifact rows, schema outlines and compact successful feature acknowledgements, changes the visible Native text subtotal from **{totals['native_response_text_tokens']:,} to {totals['projected_native_response_tokens']:,} tokens** ({saving:,} fewer). Call counts are held constant. No unobserved return is assigned a size. No reduction in navigation calls, browser calls or schema fetches is assumed.

This is a sizing experiment, **not an implemented behavior change or guaranteed saving**. Schema outlines move prose/examples out of default responses while retaining machine-readable fields and constraints. Some tasks will fetch full detail and recover that cost; validate whole-task totals and success rates. The implementation must retain every capability through an explicit, documented detail route. Request-token and image costs are not reduced by these projections.

## Reproduce and extend

```sh
uv run --project . --with-requirements scripts/audit-requirements.txt \\
  python scripts/frequency_audit.py --thread /path/to/design.md --thread /path/to/camera.md
```

Repeated `--thread` arguments retain per-thread counts and check exact payload-sequence overlap. Do not knowingly combine overlapping exports without call IDs or a documented deduplication rule. For future reliable profiling, collect per-call tool/action, counts, latency, outcome and stable trace/call IDs; keep raw CAD data out of telemetry. A cache file is never a substitute for an invocation event.

Downloads: `tools.csv` (frequency × mean × total), `calls.csv` (sanitized ordered measurements), `variants.csv`, `thread-tools.csv`, `thread-summary.csv`, `official-api-tools.csv`, `argument-fields.csv`, `transitions.csv`, `repeated-requests.csv`, `metrics.json`, and six PNG/SVG charts. The previous size audit remains intact.
'''
    (out/'README.md').write_text(text)
    charts=''.join(f'<h2>{title}</h2><a href="{file}.svg"><img src="{file}.png" alt="{title}"></a>' for file,title in [('01-frequency','Observed frequency'),('02-weighted-cost','Frequency-weighted token cost'),('06-thread-comparison','Differences between threads'),('03-frequency-size','Frequency × size'),('04-weighted-savings','Potential savings'),('05-browser-demand','Browser demand')])
    data=json.dumps(m['tools']).replace('<','\\u003c')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Onshape Native · Observed usage</title><style>body{font:16px/1.55 system-ui;background:#f8fafc;color:#17233b;max-width:1200px;margin:35px auto;padding:0 24px}h1{font-size:36px}img{width:100%}a{color:#2563eb}.note{background:#e7f0ff;padding:18px;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:8px;text-align:left;border-bottom:1px solid #dbe2eb}button{font:inherit;border:0;background:transparent;cursor:pointer}input{padding:9px}section{overflow-x:auto}h2{margin-top:35px}</style>
<h1>Frequency changes the optimization priorities</h1><p class="note">TOTALS. Text tokens only; images and missing responses excluded. Cache artifacts validate provenance, not frequency. Zero use does not mean a capability is unnecessary.</p><p><a href="../index.html">Size audit</a> · <a href="README.md">Analysis and recommendations</a> · <a href="tools.csv">Frequency CSV</a> · <a href="metrics.json">Full measurements</a></p>
<h2>All current tools, ranked by observed context cost</h2><p>Click a heading to sort. Mean = measured response text subtotal / responses present. Unobserved tools retain their full functionality.</p><input id="filter" aria-label="Filter tools" placeholder="Filter tools"><section><table><thead><tr><th><button data-k="tool">Tool ↕</button></th><th><button data-k="calls">Calls ↕</button></th><th><button data-k="share_native_calls_percent">Frequency % ↕</button></th><th><button data-k="mean_response_tokens">Mean tokens ↕</button></th><th><button data-k="response_tokens">Total tokens ↕</button></th><th><button data-k="argument_tokens">Argument tokens ↕</button></th><th><button data-k="explicit_errors">Errors ↕</button></th></tr></thead><tbody id="rows"></tbody></table></section>
CHARTS<script>const rows=DATA;let key='response_tokens',dir=-1;const fields=['tool','calls','share_native_calls_percent','mean_response_tokens','response_tokens','argument_tokens','explicit_errors'];function render(){let a=rows.filter(r=>r.tool.includes(document.querySelector('#filter').value.toLowerCase())).sort((a,b)=>key==='tool'?dir*a.tool.localeCompare(b.tool):dir*((a[key]??-1)-(b[key]??-1)));document.querySelector('#rows').innerHTML=a.map(r=>'<tr>'+fields.map(k=>'<td>'+(r[k]==null?'—':typeof r[k]==='number'?r[k].toLocaleString():r[k])+'</td>').join('')+'</tr>').join('')}document.querySelector('#filter').oninput=render;document.querySelectorAll('button[data-k]').forEach(b=>b.onclick=()=>{dir=key===b.dataset.k?-dir:-1;key=b.dataset.k;render()});render();</script></html>'''.replace('CHARTS',charts).replace('DATA',data)
    page=page.replace('TOTALS',f"{totals['native_calls']} Native calls · {totals['official_api_calls']} official API calls (separate) · {totals['browser_calls']} browser calls · {m['source']['thread_count']} threads")
    (out/'index.html').write_text(page)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--thread',type=Path,action='append',required=True);p.add_argument('--output',type=Path,default=ROOT/'docs/token-audit/usage');main(p.parse_args())
