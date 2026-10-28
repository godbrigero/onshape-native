import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {displayCommand} from '../extension/display-adapter.js';
const target={did:'a'.repeat(24),wid:'b'.repeat(24),eid:'c'.repeat(24)}, micro='d'.repeat(24);
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
function setup({parentHidden=false,offline=false,current=false,elementRevision=null,responseHook=null}={}) {
 globalThis.crypto ||= webcrypto;globalThis.location={origin:'https://cad.onshape.com',pathname:`/documents/${target.did}/w/${target.wid}/e/${target.eid}`,search:''};
 const sent=[],transforms=new Map([['part',identity.slice()]]);
 let revision=micro,closed=offline;let elementMicro=elementRevision;
 const node=(type,name,children_count=0)=>({displayName:name,childrenCount:children_count,hidden:false,suppressed:false,suppressedByParent:false,getMessageName:()=>`assembly.tree.GBTAssemblyTree${type}`});
 const root=node('Instance','Root',2),part=node('Instance','Part',1),connector=node('MateConnector','Inherited'),mate=node('Mate','Joint');
 connector.featureId='Fderived.*merge.Fconnector';connector.partStudioMateConnector=true;mate.mateType='REVOLUTE';
 const makeItem=(node,path,feature_id)=>({treeNode:node,isFeature:!!feature_id,isFolder:false,isParentHidden:parentHidden&&node===connector,
  getCanBeHidden:()=>true,getOccurrence:()=>({path}),getFeatureId:()=>feature_id,getVisibility:()=>node.hidden?1:2});
 const items=[makeItem(part,['part']),makeItem(connector,['part'],connector.featureId),makeItem(mate,[],'mate')];
 const tree={isValid:true,pathToNodes:new Map([['',root],['part',part],['part.connector',connector],['mate',mate]])};
 const classes={CJP:()=>{},D0n:()=>{},z_V:{VISIBLE:2,HIDDEN:1}};
 for (const name of ['assembly.GBTOccurrence','assembly.GBTFeatureReference','ui.assembly.GBTUiBatchVisibilityChange','ui.assembly.GBTUiChangeOccurrenceVisibility','ui.assembly.GBTUiSetFeatureOccurrenceVisibility','assembly.GBTUiAssemblyAnimateMateRequest','ui.GBTUiMeasureCall','math.GBTVector3d','bsedit.GBTMIndividualQuery','assembly.GBTMIndividualQueryWithOccurrence',...['TranslationStart','TranslationChange','RotationStart','RotationChange','DragEnd'].map(n=>'ui.assembly.drag.GBTUiAssembly'+n)]) {
  classes[name]=class {
   constructor(){this.occurrenceVisibilityCalls=[];this.featureOccurrenceVisibilityCalls=[];this.mate={};this.numFrames={};this.startValue={};this.endValue={};}
   getMessageName(){return name;}
   getPathAsString(){return this.path.join('.');}
  };
 }
 const frames=[0,Math.PI/4,Math.PI/2].map((angle,i)=>({mateDofValue:angle,changedOccurrences:[{occurrence:{path:['part'],getPathAsString:()=> 'part'},transform:{getGlMatrix:()=>{const t=identity.slice();t[12]=i;return t;}}}]}));
 const camera={getFrame:()=>identity,getViewMatrix:()=>identity,getViewport:()=>[0,0,100,100],isOrthographic:()=>true,getExtents:()=>[0,0,0,1,1,1]};
 const manager={hasGraphicsOccurrenceData:()=>true,getOccurrenceTransform:()=>transforms.get('part'),
  batchUpdateOccurrenceTransforms:changes=>{for(const c of changes)transforms.set(c.pathId,[...c.transform]);return true;}};
 const cameraViews=[];
 const viewer={getViewerId:()=>7,getPrimaryViewController:()=>({setStandardView:name=>cameraViews.push(name),updateCameraNearFar:()=>{},afterViewChange:()=>{}}),getOccurrenceIdManager:()=>({getIdForName:path=>path==='part'?1:-1}),getOccurrenceDataManager:()=>({getOccurrenceTransform:()=>transforms.get('part')}),getModelViewManagers:()=>({getManager:()=>manager}),getCamera:()=>camera,draw:()=>{}};
 const controller={connection:{isClosed:()=>closed},getActiveElementTabId:()=>target.eid,getViewer:()=>viewer,
  documentModel:{get:k=>k==='microversionId'?{theId:revision}:{get:k=>k==='microversionId'?elementMicro:'',definition:{assemblyTree:tree}}},
  elementConnection:{callAndPromise:async message=>{
   sent.push(message);
   if(responseHook) {const result=responseHook(message,transforms);if(result!==undefined)return result;}
   if(message.getMessageName().endsWith('AnimateMateRequest'))return {errorCode:0,frames};
   for(const call of message.featureOccurrenceVisibilityCalls)for(const ref of call.features){
    const item=items.find(i=>i.getFeatureId()===ref.featureId&&JSON.stringify(i.getOccurrence().path)===JSON.stringify(ref.occurrence.path));item.treeNode.hidden=call.visibility===1;
   }
   return {};
  }}};
 controller.connection.callAndPromise=controller.elementConnection.callAndPromise;
 const modules={27940:classes,3392:{GI:{getOpenDocumentController:()=>controller}},64725:{V:{itemsByPath:new Map(items.map((v,i)=>[String(i),v]))}}};
 if(current) {modules[96402]=modules[27940];modules[87539]=modules[3392];modules[65443]=modules[64725];delete modules[27940];delete modules[3392];delete modules[64725];}
 const chunks=[];chunks.push=value=>{Array.prototype.push.call(chunks,value);value[2](id=>modules[id]);};globalThis.webpackChunkNewton=chunks;
 return {controller,setElementRevision:v=>elementMicro=v,cameraViews,modules,sent,connector,mate,transforms,setRevision:v=>revision=v,setClosed:v=>closed=v};
}
const run=(operation,args={},extra={})=>displayCommand({kind:'display',target,operation,args,expected_microversion:micro,...extra});
const fingerprint=state=>state.rows.map(r=>[r.tree_path,r.visibility,r.parent_hidden,r.suppressed,r.suppressed_by_parent]);
test('complete tree includes inherited exact feature reference and effective parent hiding',async()=>{
 setup({parentHidden:true});const state=await run('inspect');assert.equal(state.complete,true);assert.equal(state.connected,true);
 const row=state.rows.find(r=>r.inherited_connector);assert.deepEqual(row.reference,{kind:'feature',occurrence_path:['part'],feature_id:'Fderived.*merge.Fconnector'});assert.equal(row.effective_visible,false);
});
test('offline editor fails before sending and stale display state fails before mutation',async()=>{
 const env=setup({offline:true});const state=await run('inspect'),ref=state.rows.at(-1).reference;
 assert.equal(state.connected,false);
 assert.match((await run('visibility',{changes:[{reference:ref,visible:false}],expected_state:fingerprint(state)})).error,/disconnected/);assert.equal(env.sent.length,0);
 env.setClosed(false);env.mate.hidden=true;
 assert.match((await run('visibility',{changes:[{reference:ref,visible:false}],expected_state:fingerprint(state)})).error,/Display state changed/);assert.equal(env.sent.length,0);
});
test('mixed visibility uses one typed batch and reads observed values',async()=>{
 const env=setup();env.connector.hidden=true;const state=await run('inspect');const rows=state.rows.filter(r=>r.reference?.kind==='feature');
 const result=await run('visibility',{changes:rows.map(r=>({reference:r.reference,visible:!r.effective_visible})),expected_state:fingerprint(state)});
 assert.equal(result.verified,true);assert.equal(env.sent.length,1);assert.equal(env.sent[0].featureOccurrenceVisibilityCalls.length,2);
 assert.equal(env.sent[0].featureOccurrenceVisibilityCalls[1].features[0].featureId,'Fderived.*merge.Fconnector');
});
test('motion uses solved angles, applies frame transforms and restores actual baseline',async()=>{
 const env=setup();const state=await run('inspect');const mate=state.rows.at(-1).reference;
 const prepared=await run('motion',{action:'prepare',mate,frames:3,start_degrees:0,end_degrees:90});assert.equal(prepared.state,'prepared');
 assert.equal(env.sent[0].mate.queryData,'Rz');const session_id=prepared.session_id;
 const step=await run('motion',{action:'step',session_id,frame:1});assert.equal(step.angle_degrees,45);assert.equal(step.pose_verified,true);assert.equal(env.transforms.get('part')[12],1);
 const restored=await run('motion',{action:'restore',session_id});assert.equal(restored.state,'restored');assert.equal(restored.angle_degrees,null);assert.deepEqual(env.transforms.get('part'),identity);
});
test('motion refuses restoring an old pose over a newer model revision',async()=>{
 const env=setup();const state=await run('inspect');const prepared=await run('motion',{action:'prepare',mate:state.rows.at(-1).reference,frames:3,start_degrees:0,end_degrees:90});
 await run('motion',{action:'step',session_id:prepared.session_id,frame:1});env.setRevision('e'.repeat(24));
 assert.match((await run('motion',{action:'restore',session_id:prepared.session_id})).error,/Model changed/);assert.equal(env.transforms.get('part')[12],1);
});
test('wrong URL fails before any editor operation',async()=>{
 const env=setup();location.pathname='/documents/elsewhere';assert.match((await run('inspect')).error,/target navigated/);assert.equal(env.sent.length,0);
});

test('current captured frontend profile resolves display rows',async()=>{
 setup({current:true});assert.equal((await run('inspect')).complete,true);
});
test('missing controller fails before display mutation with bootstrap diagnostic',async()=>{
 const env=setup({current:true});env.modules[87539]={};
 assert.match((await run('visibility')).error,/87539:controller-accessor-missing/);assert.equal(env.sent.length,0);
});
test('missing sidebar registry returns bounded diagnostic',async()=>{
 const env=setup({current:true});env.modules[65443]={};
 assert.match((await run('inspect')).error,/sidebar-registry-missing:65443/);assert.equal(env.sent.length,0);
});

test('camera changes ignore model revisions but retain connection and target guards',async()=>{
 const env=setup();env.setRevision('e'.repeat(24));
 const result=await run('camera',{action:'standard',view:'front',fit:false},{expected_microversion:''});
 assert.equal(result.applied,true);assert.deepEqual(env.cameraViews,['XZ']);assert.equal(env.sent.length,0);
 env.setClosed(true);assert.match((await run('camera',{action:'standard',view:'front',fit:false})).error,/disconnected/);
 assert.equal(env.cameraViews.length,1);
});

test('element revision isolates unrelated document changes and still rejects element changes',async()=>{
 const env=setup({elementRevision:micro});env.setRevision('e'.repeat(24));
 const state=await run('inspect');assert.equal(state.microversion,micro);assert.equal(state.document_microversion,'e'.repeat(24));
 const args={changes:[{reference:state.rows.at(-1).reference,visible:false}],expected_state:fingerprint(state)};
 assert.equal((await run('visibility',args)).verified,true);
 env.setElementRevision('f'.repeat(24));const count=env.sent.length;
 assert.match((await run('visibility',args)).error,/revision changed/);assert.equal(env.sent.length,count);
});
test('native measurement dispatches typed points and does not assert geometric verification',async()=>{
 const env=setup({responseHook:message=>message.getMessageName()==='ui.GBTUiMeasureCall'?{distance:0.005}:undefined});
 const result=await run('measure',{points_m:[[0,0,0],[0,0,0.005]]});
 assert.equal(result.result.distance,0.005);assert.equal(result.verified,undefined);
 assert.equal(env.sent.length,1);assert.equal(env.sent[0].pointPositions[1].z,0.005);assert.equal(env.sent[0].viewerId,7);
});
test('translation follows start/change/end and checks saved and rendered result',async()=>{
 const env=setup({responseHook:(message,transforms)=>{
  if(message.getMessageName().endsWith('TranslationChange')){const t=identity.slice();t[12]=message.translation.x;transforms.set('part',t);}return {};
 }});
 const result=await run('transform',{action:'translate',occurrence_paths:[['part']],translation_m:[0.025,0,0],edit_description:'Test'});
 assert.equal(result.verified,true);assert.equal(result.checks[0].actual_transform[12],0.025);
 assert.deepEqual(env.sent.map(m=>m.getMessageName().split('.').at(-1)),['GBTUiAssemblyTranslationStart','GBTUiAssemblyTranslationChange','GBTUiAssemblyDragEnd']);
 assert.equal(env.sent[1].sequenceId,1);
});
test('partial transform error prevents replay and exposes incomplete stage',async()=>{
 const env=setup({responseHook:m=>m.getMessageName().endsWith('TranslationChange')?{errorCode:3}:{}});
 const args={action:'translate',occurrence_paths:[['part']],translation_m:[0.025,0,0],edit_description:'Test'};
 assert.match((await run('transform',args)).error,/rejected at change/);assert.equal(env.sent.length,2);
 assert.equal((await run('inspect')).incomplete_transform.stage,'change');
 assert.match((await run('transform',args)).error,/incomplete/);assert.equal(env.sent.length,2);
});
test('pending native RPC cannot be overwritten by a measurement',async()=>{
 const env=setup();env.controller.__onshapeNativePendingDisplayRpc={pending:true};
 assert.match((await run('measure',{points_m:[[0,0,0]]})).error,/still pending/);assert.equal(env.sent.length,0);
});

function featureFixture() {
 let definition;
 const env=setup({responseHook:m=>{
  const type=m.getMessageName();
  if(type.endsWith('TreeItemDefinitionRequest'))return {node:definition};
  if(type.endsWith('SpecifyFeature'))definition.parameters[0]=m.featureChange.newNode;
  return {};
 }});
 const types=env.modules[27940];
 for(const [name,defaults] of Object.entries({
  'ui.assembly.GBTUiAssemblyTreeItemDefinitionRequest':{},'ui.GBTUiBeginEdit':{},'ui.GBTUiSpecifyFeature':{},'ui.GBTUiCommit':{},
  'tree.GBTNodeReference':{nodeId:''},'diff.GBTTreeEditChange':{oldNode:null,newNode:null},
  'assembly.GBTMMateGroup':{nodeId:'group',featureId:'group',parameters:[],suppressionState:null},
  'assembly.GBTMParameterQueryWithOccurrenceList':{nodeId:'parameter',parameterId:'occurrencesQuery',queries:[]},
  'assembly.GBTMIndividualOccurrenceQuery':{nodeId:'query',path:[]}
 })) types[name]=class {constructor(){Object.assign(this,structuredClone(defaults));}getMessageName(){return name;}};
 definition=new types['assembly.GBTMMateGroup']();const parameter=new types['assembly.GBTMParameterQueryWithOccurrenceList']();
 const query=new types['assembly.GBTMIndividualOccurrenceQuery']();query.path=['part'];parameter.queries=[query];definition.parameters=[parameter];
 return env;
}
test('native feature edit tolerates transport key ordering and omitted nulls and reads back membership',async()=>{
 const env=featureFixture();const read=await run('feature',{action:'read',node_id:'group',parent_occurrence_path:[]});
 const expected=JSON.parse(JSON.stringify(read.definition));expected.suppressionState=null;
 const result=await run('feature',{action:'edit',node_id:'group',parent_occurrence_path:[],expected_definition:expected,patches:[{node_id:'parameter',fields:{queries:[]}}],edit_description:'Test'});
 assert.equal(result.verified,true);assert.deepEqual(result.definition.parameters[0].queries,[]);
 assert.deepEqual(env.sent.slice(2,5).map(m=>m.getMessageName()),['ui.GBTUiBeginEdit','ui.GBTUiSpecifyFeature','ui.GBTUiCommit']);
});
test('feature identity changes and overlapping patches fail before begin',async()=>{
 const env=featureFixture();const read=await run('feature',{action:'read',node_id:'group',parent_occurrence_path:[]});
 const base={action:'edit',node_id:'group',parent_occurrence_path:[],expected_definition:read.definition,edit_description:'Test'};
 assert.match((await run('feature',{...base,patches:[{node_id:'parameter',fields:{nodeId:'changed'}}]})).error,/preserve native identity/);
 assert.match((await run('feature',{...base,patches:[{node_id:'group',fields:{parameters:[]}},{node_id:'parameter',fields:{queries:[]}}]})).error,/ancestor/);
 assert.ok(env.sent.every(m=>m.getMessageName().endsWith('TreeItemDefinitionRequest')));
});
test('rotation uses right-hand API angles despite clockwise native drag convention',async()=>{
 const env=setup({responseHook:(m,transforms)=>{
  if(m.getMessageName().endsWith('RotationChange')){const c=Math.cos(-m.angle),s=Math.sin(-m.angle);transforms.set('part',[c,s,0,0,-s,c,0,0,0,0,1,0,0,0,0,1]);}return {};
 }});
 const result=await run('transform',{action:'rotate',occurrence_paths:[['part']],origin_m:[0,0,0],axis:[0,0,1],angle_degrees:90,edit_description:'Test'});
 assert.equal(result.verified,true);assert.equal(env.sent[1].angle,-Math.PI/2);
});

test('measurement success requires actual quantities and no native error',async()=>{
 for(const [response,measured] of [[{error:0,measurements:[]},false],[{error:17,measurements:[{value:5}]},false],[{error:0,measurements:[{value:0.005,measurementType:4}]},true]]) {
  setup({responseHook:()=>response});assert.equal((await run('measure',{points_m:[[0,0,0],[0,0,0.005]]})).measured,measured);
 }
});
