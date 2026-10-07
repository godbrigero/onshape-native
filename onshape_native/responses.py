"""Progressive responses. The saved artifact always contains the original value."""
from .store import compact


def escape(key):
    return str(key).replace('~','~0').replace('/','~1')


def children(value, pointer='', offset=0, limit=40):
    items=value.items() if isinstance(value,dict) else enumerate(value) if isinstance(value,list) else []
    return [{'pointer':pointer+'/'+escape(k),'type':type(v).__name__,
             **({'count':len(v)} if isinstance(v,(dict,list,str)) else {'value':v})}
            for k,v in list(items)[offset:offset+limit]]


def respond(store, value, detail='summary', kind='', pointer='', offset=0, limit=20):
    """No write replay is required to expand a summary; use artifact_page."""
    if detail=='full' and kind=='discovery':return value
    if detail=='full' or pointer or offset or not isinstance(value,dict):
        result=store.response(value,pointer,offset,limit)
        if detail!='full' and not isinstance(value,bytes):result.pop('path',None);result.pop('bytes',None)
        return result
    saved=store.put(value);artifact=saved['artifact']
    if kind=='camera':
        return {'artifact':artifact,**{k:v for k,v in value.items() if k not in ('camera','target')},
                'details':{'tool':'artifact_page','pointer':'/camera'}}
    # Only shorten confirmed successful writes. Preserve all status/skew fields.
    feature=value.get('feature');state=value.get('featureState')
    if kind=='write' and isinstance(feature,dict) and isinstance(state,dict) and state.get('featureStatus')=='OK' and not value.get('microversionSkew'):
        data={k:v for k,v in value.items() if k!='feature'}
        data['feature']={k:v for k,v in feature.items() if k in ('featureId','featureType','name')}
        return {'artifact':artifact,'data':data,'details':{'tool':'artifact_page','pointer':'/feature'}}
    if kind=='schema' and 'operation' in value:
        # Parameter descriptions can encode units/constraints. Never strip them.
        data={k:v for k,v in value.items() if k not in ('responses','description')}
        if 'description' in value:data['description_pointer']='/description'
        return {'artifact':artifact,**store.page(data,limit=limit),
                'details':{'tool':'artifact_page','pointer':''}}
    if kind=='discovery':
        data={k:v for k,v in value.items() if k not in ('engine','index','indexed_commands','score_meaning','manual_fallback','manual_procedure')}
        if 'matches' in data:
            data['matches']=[{k:v for k,v in row.items() if k not in ('id','matched_terms','method','path')} for row in data['matches']]
        return {'artifact':artifact,**data,'details':{'tool':'artifact_page','pointer':''}}
    page=store.page(value,limit=limit,max_chars=2500 if kind=='read' else 7000)
    result={'artifact':artifact,**page}
    if page.get('needs_narrower_pointer'):
        # Store.page already supplies exact child pointers: never repeat the map.
        result.pop('keys',None)
        result.pop('hint',None)
        if isinstance(value.get('rootAssembly'),dict):
            root=value['rootAssembly']
            result['assembly']={k:len(root[k]) for k in ('instances','occurrences','features','parts') if isinstance(root.get(k),list)}
            result['assembly']['pointer']='/rootAssembly'
    return result


ROW_FIELDS={'id','kind','node_id','parent_id','name','index','element_id','element_type',
            'occurrence_path','feature_id','reference','effective_visible','visibility',
            'parent_hidden','suppressed','suppressed_by_parent','hidden','fixed','status',
            'inherited_connector','mate_type','placement','tree_path','parent_path','reason'}


def tree_page(store,data,snapshot,parent_id='',recursive=True,offset=0,limit=20,query='',node_id='',detail='summary'):
    from .structures import page_tree
    # Validate parent even when the result is empty.
    result=page_tree(store,data,snapshot,parent_id,recursive,0,1)
    rows=[]
    indices=[]
    for i,row in enumerate(data['rows']):
        if parent_id and row['parent_id']!=parent_id and not (recursive and parent_id in row.get('ancestors',[])):continue
        if node_id and row.get('id')!=node_id and row.get('element_id')!=node_id:continue
        if query and query.casefold() not in (row.get('name') or '').casefold():continue
        indices.append(i)
        rows.append(row if detail=='full' else {**{k:v for k,v in row.items() if k in ROW_FIELDS},'detail_pointer':f'/rows/{i}'})
    for key in ('data','total','next_offset','needs_narrower_pointer','type','keys','hint','next','children'):result.pop(key,None)
    result.update(store.page(rows,offset=offset,limit=limit))
    for child in result.get('children',[]):
        child['pointer']=f"/rows/{indices[int(child['pointer'][1:])]}"
    if detail=='summary' and isinstance(result.get('data'),list):
        pack_rows(result)
    result['details']={'tool':'artifact_page','pointer':'/rows'}
    return result


def pack_rows(result):
    """Lossless table encoding of projected rows; null cells denote absent fields.

    Explicit null versus missing remains distinguishable in the original artifact.
    False/zero/empty string are retained and must never be treated as absent.
    """
    rows=result['data']
    columns=list(dict.fromkeys(key for row in rows for key in row))
    result['format']='table'
    result['columns']=columns
    result['data']=[[row.get(key) for key in columns] for row in rows]
    return result
