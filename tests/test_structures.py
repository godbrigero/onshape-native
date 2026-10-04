import copy
import json

import pytest

from onshape_native.client import OnshapeError
from onshape_native.store import Store
from onshape_native.structures import document_rows, feature_rows, assembly_rows, assembly_sidebar_rows, target_from_url, page_tree
from onshape_native.structure_service import Structures
from onshape_native.catalog import Catalog

D, W, E, H = "a"*24, "b"*24, "c"*24, "d"*24
M, OLD = "e"*24, "f"*24
URL = f"https://cad.onshape.com/documents/{D}/w/{W}/e/{E}"


def group(node, name, children=()):
    return {"btType": "BTElementGroup-1458", "nodeId": node, "groupName": name, "groupId": "", "groups": list(children)}


def reference(eid=E):
    return {"btType": "BTDocumentElementReference-2484", "nodeId": "ref-"+eid, "elementId": eid}


def contents():
    return {"elements": [{"id": E, "name": "Duplicate/name", "elementType": "PARTSTUDIO", "microversionId": OLD},
                         {"id": H, "name": "Generated BOM", "elementType": "BILLOFMATERIALS", "microversionId": OLD}],
            "folders": group("root-native", "", [group("one", "Same", [group("two", "Same", [reference()])])])}


def test_nested_document_identity_hidden_tabs_and_immutable_links():
    rows, issues = document_rows(contents(), target_from_url(URL), M)
    assert not issues
    leaf = next(r for r in rows if r.get("element_id") == E)
    assert leaf["parent_id"] == "folder:two" and leaf["ancestors"] == ["root", "folder:one", "folder:two"]
    assert f"/m/{M}/" in leaf["immutable_url"]
    hidden = next(r for r in rows if r.get("element_id") == H)
    assert hidden["parent_id"] is None and hidden["placement"] == "unlisted"


def test_duplicate_references_and_unknown_types_fail_completeness():
    c = contents(); c["folders"]["groups"] += [reference(), {"btType":"Unknown", "nodeId":"unknown"}]
    _, issues = document_rows(c, target_from_url(URL), M)
    assert any("duplicate" in e.lower() for e in issues)
    assert any("Unknown" in e for e in issues)


def folder(fid, start, name="Folder"):
    return {"$type":"bsedit.GBTMFolder", "folderId":fid, "isStartFolder":start, "name":name, "nodeId":fid+str(start)}


def feat(fid):
    return {"$type":"bsedit.GBTMFeature", "featureId":fid, "featureType":"extrude", "name":fid, "nodeId":"node-"+fid}


def test_sidebar_delimiters_preserve_nested_membership_and_order():
    children = [folder("outer",True), feat("A"), folder("inner",True), feat("B"), folder("inner",False), folder("outer",False), feat("C")]
    rows, issues = feature_rows({"tree":{"children":children}}, {"features":[{"featureId":f} for f in "ABC"],"featureStates":{f:{"featureStatus":"OK"} for f in "ABC"}})
    assert not issues
    by_id = {r["id"]:r for r in rows}
    assert by_id["feature:B"]["ancestors"] == ["root","feature_folder:outer","feature_folder:inner"]
    assert by_id["feature_folder:outer"]["end_index"] == 5
    assert by_id["feature:C"]["parent_id"] == "root"
    children.pop(4)
    _, issues = feature_rows({"tree":{"children":children}}, {"features":[{"featureId":f} for f in "ABC"]})
    assert any("Unbalanced" in e or "Unclosed" in e for e in issues)


def test_sidebar_stale_native_inventory_is_not_complete():
    _, issues = feature_rows({"tree":{"children":[feat("A")]}}, {"features":[{"featureId":"B"}]})
    assert any("stale" in e for e in issues)


def assembly_fixture():
    ref = {"documentId":D, "elementId":E, "documentMicroversion":M, "configuration":"size=1"}
    sub = {**ref, "instances":[{"id":"reused/leaf", "type":"Part", "name":"Part", **ref}]}
    root = {"documentId":D,"elementId":H,"documentMicroversion":M,
            "instances":[{**ref,"id":i,"type":"Assembly","name":"Same"} for i in ["left","right"]],
            "occurrences":[{"path":[i,"reused/leaf"],"transform":[1]*16} for i in ["left","right"]]}
    return {"rootAssembly":root,"subAssemblies":[sub]}


def test_repeated_subassembly_instances_use_full_occurrence_paths():
    rows, issues = assembly_rows(assembly_fixture())
    assert not issues
    leaves = [r for r in rows if r.get("instance_id") == "reused/leaf"]
    assert len(leaves)==2 and len({r["id"] for r in leaves})==2
    assert leaves[0]["parent_id"] != leaves[1]["parent_id"]
    assert all(r["transform"]==[1]*16 for r in leaves)
    assert all("configuration=size%3D1" in r["reference_url"] for r in leaves)


def test_missing_subassembly_definition_is_not_silently_flattened():
    data=assembly_fixture();data["subAssemblies"]=[]
    rows,issues=assembly_rows(data)
    assert issues and any(r.get("children_complete") is False for r in rows)


def assembly_sidebar_fixture():
    def n(typ, name, count=0, index=0):
        return {"$type":"assembly.tree.GBTAssemblyTree"+typ,"displayName":name,"childrenCount":count,"indexInParent":index,"commonFlags":0}
    return {"assemblyTreeValid":True,"assemblyTree":{"pathToNodes":{"$map":[
        ["",n("Instance","Assembly",2)], ["Fone",n("Folder","Parts",1)],
        ["Fone.Mpart",n("Instance","Part")], ["mateList",n("Folder","Mates",1,1)],
        ["mateList.Fmates",n("Folder","Connections",1)], ["mateList.Fmates.Mmate",n("Mate","Fastened")]]}}}


def test_assembly_sidebar_folder_ids_survive_display_moves():
    native=assembly_sidebar_fixture();rows,issues=assembly_sidebar_rows(native)
    assert not issues
    part=next(r for r in rows if r.get("name")=="Part")
    assert part["id"]=='assembly_node:["Mpart"]' and part["parent_id"]=='assembly_node:["Fone"]'
    assert not part["owner_occurrence_path"]
    mate=next(r for r in rows if r.get("name")=="Fastened")
    assert mate["category"]=='mates' and mate["id"]=='assembly_node:["Mmate"]'
    native['assemblyTree']['pathToNodes']['$map'][2][0]='Mpart'
    newer,_=assembly_sidebar_rows(native)
    assert next(r for r in newer if r.get('name')=='Part')['id']==part['id']


def test_assembly_sidebar_missing_map_and_lazy_children_are_explicit():
    assert assembly_sidebar_rows({'assemblyTree':{'pathToNodes':{}}})[1]
    native=assembly_sidebar_fixture();native['assemblyTree']['pathToNodes']['$map'].pop()
    assert any('Incomplete' in i for i in assembly_sidebar_rows(native)[1])


async def test_assembly_sidebar_noop_ack_fails_verification(tmp_path):
    from onshape_native.assembly_sidebar import edit_assembly_sidebar
    s=FakeService(tmp_path);a=Structures(s)
    rows,issues=assembly_sidebar_rows(assembly_sidebar_fixture())
    data={'kind':'onshape-structure','tree_kind':'assembly','complete':True,'target':target_from_url(URL),
          'url':URL,'microversion':M,'rows':rows,'issues':issues}
    async def capture(url):return copy.deepcopy(data)
    a.capture_element=capture
    result=await edit_assembly_sidebar(a,data,'rename',['assembly_node:["Fone"]'],'New','root','',False,None,None)
    assert result['structure_verified'] is False
    sent=next(j for j in s.client.sent if j['kind']=='native')
    assert sent['body']['featureChange']['fieldIndex']==14856192


class FakeClient:
    def __init__(self): self.sent=[]
    async def command(self, job):
        self.sent.append(job)
        if job["kind"]=="open":return {"tab_id":1}
        if job["kind"]=="state":return {"microversion":M,"editingFeatureId":None}
        if job["kind"]=="schema":return {"defaults":{"nodeId":"new-folder"}}
        return {"result":{"ack":True},"microversion_before":M,"microversion_after":M}


class FakeService:
    def __init__(self, tmp_path):
        self.store=Store(tmp_path);self.client=FakeClient();self.catalog=Catalog();self.micro=M;self.calls=[];self.content=contents()
    async def call(self, name, path, query=None, body=None):
        self.calls.append((name,path,query,body))
        if name=="getCurrentMicroversion":return {"microversion":self.micro}
        if name=="getDocumentContents":return copy.deepcopy(self.content)
        raise AssertionError(name)


async def test_pinned_document_reads_local_snapshot_paging_and_wrong_url(tmp_path):
    s=FakeService(tmp_path);a=Structures(s)
    tree=await a.document_tree(URL,limit=2)
    assert s.calls[1][1]["wvm"]=="m" and s.calls[1][1]["wvmid"]==M
    count=len(s.calls)
    page=await a.document_tree(URL,snapshot=tree["snapshot"],parent_id="folder:one",recursive=False)
    assert len(s.calls)==count and [r["id"] for r in page["data"]]==["folder:two"]
    with pytest.raises(OnshapeError): await a.document_tree(URL.replace(E,H),snapshot=tree["snapshot"])


async def test_stale_snapshot_and_descendant_cycle_refused_before_writing(tmp_path):
    s=FakeService(tmp_path);a=Structures(s);tree=await a.document_tree(URL)
    s.micro=OLD
    with pytest.raises(OnshapeError,match="Stale"): await a.document_edit(tree["snapshot"],"rename",node_id="folder:one",name="new")
    assert not s.client.sent
    s.micro=M
    with pytest.raises(OnshapeError,match="descendants"): await a.document_edit(tree["snapshot"],"move",node_id="folder:one",parent_id="folder:two")
    with pytest.raises(OnshapeError,match="nonempty"): await a.document_edit(tree["snapshot"],"delete_folder",node_id="folder:one")
    assert not s.client.sent


async def test_acknowledged_noop_is_not_reported_as_verified(tmp_path):
    s=FakeService(tmp_path);a=Structures(s);tree=await a.document_tree(URL)
    result=await a.document_edit(tree["snapshot"],"create_folder",name="Expected new folder")
    assert result["verified"] is False
    assert any(j["kind"]=="native" for j in s.client.sent)


async def test_create_tab_rejects_invalid_parent_before_mutation(tmp_path):
    s=FakeService(tmp_path);a=Structures(s);tree=await a.document_tree(URL)
    with pytest.raises(OnshapeError, match="Destination"):
        await a.document_edit(tree["snapshot"], "create_element", name="New", parent_id="element:"+E)
    assert not s.client.sent
    assert all(n in {"getCurrentMicroversion", "getDocumentContents"} for n,*_ in s.calls)


async def test_cascade_stops_and_reports_partial_deletion(tmp_path):
    s=FakeService(tmp_path);a=Structures(s);tree=await a.document_tree(URL)
    base=a.document_edit; steps=[]
    async def controlled(snapshot, action, **kwargs):
        steps.append((action,kwargs["node_id"]))
        if action == "delete_element": return {"verified":True,"snapshot":snapshot}
        raise OnshapeError("test failure")
    a.document_edit=controlled
    result=await base(tree["snapshot"], "delete_folder", node_id="folder:one", delete_contents=True)
    assert not result["verified"]
    assert result["completed"] == [{"action":"delete_element", "id":"element:"+E}]
    assert steps == [("delete_element","element:"+E),("delete_folder","folder:two")]


async def test_element_history_compares_ids_not_description_labels(tmp_path):
    s=FakeService(tmp_path);a=Structures(s);base=s.call
    async def call(name,path,query=None,body=None):
        if name=="getDocumentHistory":return [{"microversionId":M,"nextMicroversionId":OLD,"description":"Duplicate/name :: changed it"}]
        return await base(name,path,query,body)
    s.call=call
    result=await a.history(URL,element_id=E,limit=1)
    assert result["events"]==[] and result["next_cursor"]==OLD and result["scanned"]==1


@pytest.mark.parametrize("url", ["http://cad.onshape.com/documents/a", "https://evil.example/documents/a", URL.replace("/w/","/x/")])
def test_wrong_origin_and_malformed_url(url):
    with pytest.raises(OnshapeError):target_from_url(url)
