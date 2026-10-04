import asyncio
import json

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from onshape_native.bridge import Broker, BridgeError, create_app, validate_job
from onshape_native.native_catalog import catalog

CONFIG = {"host": "127.0.0.1", "port": 8766, "token": "test-" * 10}
TARGET = {"did": "a" * 24, "wid": "b" * 24, "eid": "c" * 24}
AUTH = {"Authorization": "Bearer " + CONFIG["token"]}


async def test_http_auth_host_origin_and_offline_behavior():
    app = create_app(CONFIG)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8766") as client:
        assert (await client.get("/health")).status_code == 401
        assert (await client.get("/health", headers={**AUTH, "Origin": "https://evil.example"})).status_code == 403
        assert (await client.get("/health", headers={**AUTH, "Host": "evil.example"})).status_code == 403
        assert (await client.get("/health", headers=AUTH)).json()["extension_connected"] is False
        response = await client.post("/command", headers=AUTH, json={"kind": "tabs"})
        assert response.status_code == 400 and "disconnected" in response.json()["error"]


async def test_local_discovery_auth_offline_and_allowlisted_dispatch():
    app = create_app(CONFIG)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8766") as c:
        path = "/local/search_commands"
        assert (await c.post(path, json={"task":"create an assembly"})).status_code == 401
        assert (await c.post(path, headers={**AUTH, "Origin":"https://evil.example"}, json={})).status_code == 403
        result = await c.post(path, headers=AUTH, json={"task":"create an assembly"})
        assert result.status_code == 200 and len(result.json()["matches"]) == 10
        assert (await c.post("/local/api_write", headers=AUTH, json={})).status_code == 404
        for args in [[], {}, {"task":"create", "unknown":True}, {"task":"create", "limit":"10"}]:
            assert (await c.post(path, headers=AUTH, json=args)).status_code == 400
        all_rest = await c.post("/local/browse_commands", headers=AUTH, json={"source":"rest", "limit":1})
        assert all_rest.json()["total"] == 302 and all_rest.json()["next_offset"] == 1
        bad_delete = await c.post("/local/document_edit", headers=AUTH,
                                  json={"snapshot":"not-read", "action":"delete_folder", "delete_contents":"false"})
        assert bad_delete.status_code == 400 and "bool" in bad_delete.json()["error"]
        url = "https://cad.onshape.com/documents/" + "a"*24 + "/w/" + "b"*24
        resolved = await c.post("/local/resolve_target", headers=AUTH, json={"url":url})
        assert resolved.status_code == 200 and resolved.json()["target"]["eid"] is None
        invalid = await c.post("/local/resolve_target", headers=AUTH, json={"url":url,"tab_id":True})
        assert invalid.status_code == 400


@pytest.mark.parametrize("path", ["https://evil.example/api/x", "//evil.example/api/x", "/api/../users", "/api/%252e%252e/users", "/api/x?x=1", "/api/x%23y", "/api/clientinfo/xsrf", "/api/v14/apikeys"])
def test_no_arbitrary_origins_traversal_or_auth_export(path):
    with pytest.raises(BridgeError):
        validate_job({"kind": "rest", "path": path, "method": "GET"})


def test_native_target_evidence_and_revision_are_required():
    job = {"kind": "native", "command": "partstudiofolders.GBTUiCreateFolder", "body": {}, "target": TARGET}
    with pytest.raises(BridgeError, match="microversion"):
        validate_job(job)
    assert validate_job({**job, "expected_microversion": "d" * 24})
    with pytest.raises(BridgeError, match="schema"):
        validate_job({**job, "command": "executeJavascript", "expected_microversion": "d" * 24})
    with pytest.raises(BridgeError, match="target"):
        validate_job({"kind": "state", "target": {"did": "a" * 24}})


async def test_timeout_is_not_replayed_and_late_result_cannot_resolve_next_command():
    broker = Broker(CONFIG)
    class Connection:
        sent = []
        async def send_json(self, data): self.sent.append(data)
    broker.extension = Connection()
    with pytest.raises(BridgeError, match="outcome unknown"):
        await broker.dispatch({"kind": "tabs"}, timeout=.01)
    assert len(broker.extension.sent) == 1
    assert not broker.pending
    task = asyncio.create_task(broker.dispatch({"kind": "tabs"}, timeout=1))
    await asyncio.sleep(.01)
    assert broker.extension.sent[0]["id"] != broker.extension.sent[1]["id"]
    broker.pending[broker.extension.sent[1]["id"]].set_result({"tabs": []})
    assert await task == {"tabs": []}


def test_websocket_requires_extension_origin_and_token():
    with TestClient(create_app(CONFIG), base_url="http://127.0.0.1:8766") as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/extension", headers={"origin": "https://evil.example"}): pass
        with client.websocket_connect("/extension", headers={"origin": "chrome-extension://" + "a" * 32}) as ws:
            ws.send_json({"token": CONFIG["token"]})
            assert ws.receive_json() == {"type": "ready", "protocol": 1}
            assert client.get("/health", headers=AUTH).json()["extension_connected"] is True
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        assert client.get("/health", headers=AUTH).json()["extension_connected"] is False


async def test_rest_preserves_path_query_json_and_status():
    app = create_app(CONFIG)
    seen = []
    async def dispatch(job):
        seen.append(job)
        return {"status": 201, "body": {"id": "created"}}
    app.state.broker.dispatch = dispatch
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8766", headers=AUTH) as client:
        response = await client.post("/api/v17/documents?x=1&x=2", json={"name": "Example", "isPublic": False})
    assert response.status_code == 201 and response.json() == {"id": "created"}
    assert seen == [{"kind": "rest", "method": "POST", "path": "/api/v17/documents", "query": {"x": ["1", "2"]}, "body": {"name": "Example", "isPublic": False}}]


def test_captured_evidence_contains_geometry_dimensions_and_folders():
    names = {row["command"] for row in catalog()}
    assert {"ui.sketch.GBTUiSketchAddRectangleCall", "ui.sketch.GBTUiSketchAddCircleCall", "ui.sketch.GBTUiSketchModifyDimensionCall", "partstudiofolders.GBTUiCreateFolder"} <= names
    assert next(row for row in catalog() if row["command"] == "ui.GBTUiMassPropCall")["replay_verified"]


async def test_binary_upload_download_and_empty_success():
    import base64
    app = create_app(CONFIG)
    seen = []
    async def dispatch(job):
        seen.append(job)
        if job["method"] == "DELETE": return {"status": 204, "body": {}}
        return {"status": 200, "encoding": "base64", "body": base64.b64encode(b"\x00\xffSTEP").decode(), "contentType": "application/octet-stream"}
    app.state.broker.dispatch = dispatch
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8766", headers=AUTH) as c:
        r = await c.post("/api/v17/blobelements", content=b"\x00\xffupload", headers={"Content-Type":"multipart/form-data; boundary=test"})
        assert r.content == b"\x00\xffSTEP"
        assert base64.b64decode(seen[0]["body_base64"]) == b"\x00\xffupload"
        assert seen[0]["content_type"] == "multipart/form-data; boundary=test"
        r = await c.delete("/api/v17/documents/test")
        assert r.status_code == 204 and not r.content


def test_ui_fallback_requires_reason_snapshot_and_revision():
    job = {"kind":"ui_action", "target":TARGET, "action":"click", "control":0,
           "snapshot":"snapshot", "expected_microversion":"d"*24}
    with pytest.raises(BridgeError, match="backend"):
        validate_job(job)
    assert validate_job({**job, "backend_unavailable_reason":"Opening an editor-only view panel"})


@pytest.mark.parametrize('job', [
    {'kind':'rest','path':42,'method':'GET'},
    {'kind':'rest','path':'/api/documents','method':'GET','query':[]},
    {'kind':'state','target':None},
    {'kind':'state','target':[]},
])
def test_malformed_jobs_are_validation_errors(job):
    with pytest.raises(BridgeError): validate_job(job)


async def test_conditional_range_headers_and_json_shapes():
    app=create_app(CONFIG);seen=[]
    async def dispatch(job):
        seen.append(job)
        if job['method']=='GET': return {'status':304,'body':None,'response_headers':{'etag':'sample-etag'}}
        return {'status':200,'body':job['body']}
    app.state.broker.dispatch=dispatch
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://127.0.0.1:8766',headers=AUTH) as c:
        r=await c.get('/api/v17/documents',headers={'If-None-Match':'sample-etag','Range':'bytes=0-99'})
        assert r.status_code==304 and not r.content and r.headers['etag']=='sample-etag'
        assert seen[-1]['request_headers']=={'if-none-match':'sample-etag','range':'bytes=0-99'}
        for value in ([{'a':1}],42,'value',None):
            r=await c.post('/api/v17/documents',content=json.dumps(value),headers={'Content-Type':'application/json'})
            assert r.json()==value


def test_authentication_is_browser_owned_but_userinfo_is_available():
    with pytest.raises(BridgeError,match='Authentication'):
        validate_job({'kind':'rest','method':'POST','path':'/api/v17/users/session'})
    assert validate_job({'kind':'rest','method':'GET','path':'/api/v17/users/sessioninfo'})


async def test_signed_export_download_never_forwards_bridge_credentials(monkeypatch):
    import base64
    real_client=httpx.AsyncClient
    seen=[]
    def download(request):
        seen.append(request)
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200,content=b'binary-stl',headers={'content-type':'application/octet-stream'})
    monkeypatch.setattr('onshape_native.bridge.httpx.AsyncClient',lambda **kwargs:real_client(**kwargs,transport=httpx.MockTransport(download)))
    broker=Broker(CONFIG)
    class Extension:
        async def send_json(self,data):
            broker.pending[data['id']].set_result({'status':307,'download_redirect':'https://sample.s3.amazonaws.com/export?signature=sample'})
    broker.extension=Extension()
    result=await broker.dispatch({'kind':'rest','method':'GET','path':'/api/v17/partstudios/sample/stl'})
    assert base64.b64decode(result['body'])==b'binary-stl' and len(seen)==1


@pytest.mark.parametrize('url',['http://127.0.0.1/secrets','https://localhost/secrets','https://evil.example/file','https://cad.onshape.com@evil.example/file'])
async def test_export_redirect_cannot_access_arbitrary_hosts(url):
    broker=Broker(CONFIG)
    class Extension:
        async def send_json(self,data):broker.pending[data['id']].set_result({'status':307,'download_redirect':url})
    broker.extension=Extension()
    with pytest.raises(BridgeError):
        await broker.dispatch({'kind':'rest','method':'GET','path':'/api/v17/partstudios/sample/stl'})


async def test_raw_http_preserves_encoded_entity_ids_and_explicit_json_null():
    app=create_app(CONFIG);seen=[]
    async def dispatch(job):seen.append(job);return {'status':200,'body':{}}
    app.state.broker.dispatch=dispatch
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://127.0.0.1:8766',headers=AUTH) as c:
        await c.get('/api/v17/assemblies/instance/nodeid/MOGxWy5ZQOQ%2FeBNbO')
        assert seen[-1]['path'].endswith('MOGxWy5ZQOQ%2FeBNbO')
        await c.post('/api/v17/documents',content='null',headers={'Content-Type':'application/json'})
        assert seen[-1]['body'] is None and seen[-1]['body_present'] is True
