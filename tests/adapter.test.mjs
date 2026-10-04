import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {pageCommand} from '../extension/page-adapter.js';

const target = {did:'a'.repeat(24),wid:'b'.repeat(24),eid:'c'.repeat(24)};
const micro = 'd'.repeat(24);
class Folder {
  constructor(){this.elementId='';this.messageId='';this.folderName='';this.begin=null;this.end=null;this.editDescription='';}
  getMessageName(){return 'partstudiofolders.GBTUiCreateFolder';}
  getClassId(){return 2538;}
}
class Location {
  constructor(){this.nodeId='';this.before=true;this.childFieldIndex=-1;}
  getMessageName(){return 'tree.GBTInsertionLocation';}
}
let sent=[];
function setup(definition){
  globalThis.crypto ||= webcrypto;
  globalThis.location = {origin:'https://cad.onshape.com',pathname:`/documents/${target.did}/w/${target.wid}/e/${target.eid}`};
  sent=[];
  const controller = {getActiveElementTabId:()=>target.eid,
    documentModel:{get:k=>k==='microversionId'?{theId:micro}:{get:()=>null,definition}},
    documentClientCache:{getModelTreeState:()=>({diffableModelTree:{getRoot:()=>({children:[]})}})},
    elementConnection:{callAndPromise:async m=>{sent.push(m);return {errorEnum:0};}}};
  const modules = {27940:{CJP:()=>{},D0n:()=>{},Folder,Location},3392:{GI:{getOpenDocumentController:()=>controller}}};
  const chunks=[];chunks.push=value=>{Array.prototype.push.call(chunks,value);value[2](id=>modules[id]);};
  globalThis.webpackChunkNewton=chunks;
}
test('exact target and revision checked before mutation',async()=>{
  setup();const job={kind:'native',target,command:'partstudiofolders.GBTUiCreateFolder',body:{folderName:'Test'},expected_microversion:'e'.repeat(24)};
  assert.match((await pageCommand(job)).error,/revision changed/);assert.equal(sent.length,0);
  globalThis.location.pathname='/documents';assert.match((await pageCommand({...job,expected_microversion:micro})).error,/navigated/);assert.equal(sent.length,0);
});
test('typed nested messages reach native connection and caller IDs are replaced',async()=>{
  setup();await pageCommand({kind:'native',target,command:'partstudiofolders.GBTUiCreateFolder',expected_microversion:micro,
    body:{folderName:'Test',messageId:'captured',begin:{$type:'tree.GBTInsertionLocation',nodeId:'current-node'}}});
  assert.equal(sent.length,1);assert.ok(sent[0] instanceof Folder);assert.ok(sent[0].begin instanceof Location);assert.notEqual(sent[0].messageId,'captured');
});
test('schema drift and prototype fields fail before sending',async()=>{
  setup();const base={kind:'native',target,command:'partstudiofolders.GBTUiCreateFolder',expected_microversion:micro};
  assert.match((await pageCommand({...base,body:{inventedField:1}})).error,/Unknown.*field/);
  assert.match((await pageCommand({...base,body:JSON.parse('{"__proto__":{}}')})).error,/Invalid native field/);
  assert.equal(sent.length,0);
});
test('state returns the native tree and microversion without HTTP',async()=>{
  setup();const state=await pageCommand({kind:'state',target});assert.equal(state.microversion,micro);assert.deepEqual(state.tree,{children:[]});assert.equal(sent.length,0);
});

test('assembly sidebar Map entries survive serialization with typed nodes',async()=>{
  const node={displayName:'Folder',childrenCount:0,getMessageName(){return 'assembly.tree.GBTAssemblyTreeFolder'}};
  setup({assembly:{nodeId:'root'},assemblyTree:{isValid:true,pathToNodes:new Map([['Ffolder',node]])}});
  const state=await pageCommand({kind:'state',target});
  assert.equal(state.assemblyTreeValid,true);
  assert.deepEqual(state.assemblyTree.pathToNodes.$map,[['Ffolder',{$type:'assembly.tree.GBTAssemblyTreeFolder',displayName:'Folder',childrenCount:0}]]);
});

test('REST preserves errors and download metadata without forwarding CSRF on GET redirects',async()=>{
  setup();globalThis.document={cookie:'XSRF-TOKEN=test-cookie'};
  let request;
  globalThis.fetch=async(url,options)=>{request=options;return new Response(JSON.stringify({message:'Invalid parameter',status:400}),{status:400,headers:{'content-type':'application/json','etag':'version'}});};
  const result=await pageCommand({kind:'rest',path:'/api/v17/documents',method:'GET',request_headers:{'If-None-Match':'version'}});
  assert.equal(result.status,400);assert.equal(result.body.message,'Invalid parameter');assert.equal(result.response_headers.etag,'version');
  assert.equal(request.redirect,'follow');assert.equal(request.credentials,'same-origin');assert.equal(request.headers['X-XSRF-TOKEN'],undefined);
  assert.equal(request.headers['If-None-Match'],'version');
  await pageCommand({kind:'rest',path:'/api/v17/documents',method:'POST',body:{name:'sample'}});
  assert.equal(request.redirect,'error');assert.equal(request.headers['X-XSRF-TOKEN'],'test-cookie');
});

test('runtime rejection returns a structured diagnostic rather than a discarded promise',async()=>{
  setup();delete globalThis.webpackChunkNewton;
  const result=await pageCommand({kind:'state',target});assert.match(result.error,/runtime unavailable/);assert.match(result.outcome,/Inspect/);
});

test('extension GET observes only its own redirect Location and removes the listener',async()=>{
  const {restGet}=await import('../extension/rest-get.js');
  let listener,removed=false;
  globalThis.chrome={runtime:{id:'a'.repeat(32)},webRequest:{onHeadersReceived:{addListener(fn){listener=fn},removeListener(fn){removed=fn===listener}}}};
  globalThis.fetch=async(url,options)=>{
    assert.equal(options.redirect,'manual');assert.equal(options.credentials,'include');assert.equal(options.headers['X-XSRF-TOKEN'],undefined);
    listener({url:url.href,method:'GET',initiator:'https://cad.onshape.com',statusCode:307,responseHeaders:[{name:'Location',value:'https://wrong.example'}]});
    listener({url:url.href,method:'GET',initiator:`chrome-extension://${chrome.runtime.id}`,statusCode:307,responseHeaders:[{name:'Location',value:'https://sample.s3.amazonaws.com/sample'},{name:'set-cookie',value:'must-not-escape'}]});
    return {type:'opaqueredirect'};
  };
  const result=await restGet({kind:'rest',method:'GET',path:'/api/v17/export'});
  assert.equal(result.download_redirect,'https://sample.s3.amazonaws.com/sample');assert.ok(removed);assert.ok(!JSON.stringify(result).includes('must-not-escape'));
});
