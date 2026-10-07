import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from onshape_native.responses import respond, tree_page
from onshape_native.service import Service
from onshape_native.store import Store, compact


def feature_result(status='OK', skew=False):
    return {'feature': {'featureId':'f1', 'name':'Extrude', 'featureType':'extrude',
                        'parameters':[{'expression':'10 mm', 'queries':['face']}]*80},
            'featureState':{'featureStatus':status}, 'sourceMicroversion':'revision',
            'microversionSkew':skew, 'libraryVersion':2500}


async def test_write_once_then_expand_exact_original(tmp_path):
    store=Store(tmp_path)
    raw=feature_result()
    service=SimpleNamespace(store=store, catalog=SimpleNamespace(resolve=lambda *a:('POST','/x')),
                            call=AsyncMock(return_value=raw))
    result=await Service.write(service,'addPartStudioFeature',{},None,
                               {'sourceMicroversion':'old','rejectMicroversionSkew':True})
    assert service.call.await_count==1
    assert result['data']['sourceMicroversion']=='revision'
    assert result['data']['feature']=={'featureId':'f1','name':'Extrude','featureType':'extrude'}
    assert store.read(result['artifact'])==raw
    expanded=store.page(store.read(result['artifact']),'/feature')
    assert expanded['data']==raw['feature']
    assert service.call.await_count==1
    assert len(compact(result))<len(compact(raw))/4


@pytest.mark.parametrize('status,skew',[('ERROR',False),('OK',True),('WARNING',False)])
def test_unverified_writes_keep_feature_details(tmp_path,status,skew):
    raw=feature_result(status,skew)
    result=respond(Store(tmp_path),raw,kind='write')
    assert result['data']['feature']==raw['feature']


def test_schema_discovery_and_full_escape_hatch(tmp_path):
    store=Store(tmp_path)
    schema={'operation':'create','parameters':[{'required':True,'description':'length in meters'}],
            'requestBody':{'required':True},'responses':{'200':{'schema':'full'}}}
    result=respond(store,schema,kind='schema')
    assert result['data']=={k:v for k,v in schema.items() if k!='responses'}
    assert store.page(store.read(result['artifact']),'/responses')['data']==schema['responses']
    discovery={'matches':[{'id':'x','invoke':{'tool':'api_read'},'evidence':'observed','matched_terms':['x']}],
               'manual_procedure':['search all']}
    result=respond(store,discovery,kind='discovery')
    assert result['matches'][0]['invoke']=={'tool':'api_read'}
    assert store.read(result['artifact'])==discovery
    assert respond(store,discovery,detail='full',kind='discovery')==discovery


def test_paging_preserves_every_item_and_escaped_child_offsets(tmp_path):
    store=Store(tmp_path)
    raw=[{'index':i,'payload':'x'*1500} for i in range(14)]
    offset=0; recovered=[]
    while offset is not None:
        page=store.page(raw,offset=offset)
        recovered.extend(page['data']);offset=page['next_offset']
    assert recovered==raw
    raw={'a/b~c':['small','large'*2000]}
    page=store.page(raw,'/a~1b~0c',offset=1,limit=1)
    assert page['children'][0]['pointer']=='/a~1b~0c/1'
    text='';offset=0
    while offset is not None:
        page=store.page(raw,'/a~1b~0c/1',offset=offset)
        text+=page['data'];offset=page['next_offset']
    assert text==raw['a/b~c'][1]


def test_tree_filters_original_pointers_and_completeness(tmp_path):
    store=Store(tmp_path)
    raw={'tree_kind':'document','microversion':'m','complete':False,'issues':['unlisted tab'],
         'rows':[{'id':'root','parent_id':None,'name':None},
                 {'id':'f','parent_id':'root','name':'Motor','url':'https://example','element_id':'e'}]}
    snapshot=store.put(raw)['artifact']
    result=tree_page(store,raw,snapshot,query='motor')
    assert not result['complete'] and result['issues']==raw['issues']
    row=dict(zip(result['columns'],result['data'][0]))
    assert result['format']=='table' and row['detail_pointer']=='/rows/1'
    assert 'url' not in row
    assert store.page(store.read(snapshot),'/rows/1')['data']==raw['rows'][1]
    assert tree_page(store,raw,snapshot,node_id='e',detail='full')['data']==[raw['rows'][1]]


def test_camera_ack_retains_restoration_id_and_full_state(tmp_path):
    store=Store(tmp_path)
    raw={'camera_id':'saved','microversion':'m','camera':{'matrix':list(range(16))},'target':{'eid':'e'}}
    result=respond(store,raw,kind='camera')
    assert result['camera_id']=='saved' and result['microversion']=='m'
    assert store.read(result['artifact'])==raw
    assert 'camera' not in result


async def test_mcp_contract_stays_35_tools_with_one_expander(tmp_path,monkeypatch):
    from onshape_native import server
    monkeypatch.setattr(server,'service',SimpleNamespace(store=Store(tmp_path)))
    tools=await server.mcp.list_tools()
    assert len(tools)==35
    assert sum(t.name=='artifact_page' for t in tools)==1
    result=json.loads(server.search_commands('create an assembly'))
    expanded=json.loads(server.artifact_page(result['artifact'],'/manual_fallback'))
    assert 'data' in expanded
    assert len(result['matches'])==10


def test_large_filtered_tree_children_point_to_original_snapshot(tmp_path):
    store=Store(tmp_path)
    raw={'tree_kind':'document','microversion':'m','complete':True,'issues':[],
         'rows':[{'id':'skip','parent_id':None,'name':'Other'},
                 {'id':'wanted','parent_id':None,'name':'Wanted','metadata':'x'*8000}]}
    snapshot=store.put(raw)['artifact']
    result=tree_page(store,raw,snapshot,query='Wanted',detail='full')
    assert result['needs_narrower_pointer']
    assert result['children'][0]['pointer']=='/rows/1'
    assert store.page(store.read(snapshot),'/rows/1/metadata')['data']=='x'*6998


def test_table_preserves_false_zero_empty_and_full_detail_pointer():
    from onshape_native.responses import pack_rows
    rows=[{'id':'a','hidden':False,'index':0,'name':'','detail_pointer':'/rows/4'},
          {'id':'b','hidden':True,'name':'B','detail_pointer':'/rows/8'}]
    table=pack_rows({'data':rows})
    decoded=[dict(zip(table['columns'],row)) for row in table['data']]
    assert all(decoded[i][k]==v for i,row in enumerate(rows) for k,v in row.items())
    assert decoded[1]['index'] is None


def test_schema_long_operation_prose_is_retrievable(tmp_path):
    store=Store(tmp_path)
    raw={'operation':'write','description':'Important operation semantics. '*100,
         'parameters':[{'name':'length','description':'meters; positive only','required':True}],
         'responses':{'200':{'description':'ok'}}}
    result=respond(store,raw,kind='schema')
    assert result['data']['parameters']==raw['parameters']
    assert result['data']['description_pointer']=='/description'
    assert store.page(store.read(result['artifact']),'/description')['data']==raw['description']


def test_default_read_budget_does_not_change_explicit_detail(tmp_path):
    store=Store(tmp_path);raw={'a':'x'*3000}
    result=respond(store,raw,kind='read')
    assert result['needs_narrower_pointer']
    assert 'details' not in result and 'keys' not in result
    assert result['children'][0]['pointer']=='/a'
    assert respond(store,raw,detail='full',kind='read')['data']==raw
    assert respond(store,raw,kind='read',pointer='/a')['data']==raw['a']
