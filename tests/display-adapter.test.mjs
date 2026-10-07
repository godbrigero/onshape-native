import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {displayCommand} from '../extension/display-adapter.js';
const target={did:'a'.repeat(24),wid:'b'.repeat(24),eid:'c'.repeat(24)}, micro='d'.repeat(24);
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
function setup({parentHidden=false,offline=false}={}) {
 globalThis.crypto ||= webcrypto;globalThis.location={origin:'https://cad.onshape.com',pathname:`/documents/${target.did}/w/${target.wid}/e/${target.eid}`,search:''};
 const sent=[],transforms=new Map([['part',identity.slice()]]);
 let revision=micro,closed=offline;
 const node=(type,name,children_count=0)=>({displayName:name,childrenCount:children_count,hidden:false,suppressed:false,suppressedByParent:false,getMessageName:()=>`assembly.tree.GBTAssemblyTree${type}`});
 const root=node('Instance','Root',2),part=node('Instance','Part',1),connector=node('MateConnector','Inherited'),mate=node('Mate','Joint');
 connector.featureId='Fderived.*merge.Fconnector';connector.partStudioMateConnector=true;mate.mateType='REVOLUTE';
 const makeItem=(node,path,feature_id)=>({treeNode:node,isFeature:!!feature_id,isFolder:false,isParentHidden:parentHidden&&node===connector,
  getCanBeHidden:()=>true,getOccurrence:()=>({path}),getFeatureId:()=>feature_id,getVisibility:()=>node.hidden?1:2});
 const items=[makeItem(part,['part']),makeItem(connector,['part'],connector.featureId),makeItem(mate,[],'mate')];
 const tree={isValid:true,pathToNodes:new Map([['',root],['part',part],['part.connector',connector],['mate',mate]])};
 const classes={z_V:{VISIBLE:2,HIDDEN:1}};
 for (const name of ['assembly.GBTOccurrence','assembly.GBTFeatureReference','ui.assembly.GBTUiBatchVisibilityChange','ui.assembly.GBTUiChangeOccurrenceVisibility','ui.assembly.GBTUiSetFeatureOccurrenceVisibility','assembly.GBTUiAssemblyAnimateMateRequest']) {
  classes[name]=class {
   constructor(){this.occurrenceVisibilityCalls=[];this.featureOccurrenceVisibilityCalls=[];this.mate={};this.numFrames={};this.startValue={};this.endValue={};}
   getMessageName(){return name;}
   getPathAsString(){return this.path.join('.');}
  };
 }
 const frames=[0,Math.PI/4,Math.PI/2].map((angle,i)=>({mateDofValue:angle,changedOccurrences:[{occurrence:{path:['part'],getPathAsString:()=> 'part'},transform:{getGlMatrix:()=>{const t=identity.slice();t[12]=i;return t;}}}]}));
 const camera={getFrame:()=>identity,getViewMatrix:()=>identity,getViewport:()=>[0,0,100,100],isOrthographic:()=>true,getExtents:()=>[0,0,0,1,1,1]};
 const manager={hasGraphicsOccurrenceData:()=>true,getOccurrenceTransform:()=>identity.slice(),
  batchUpdateOccurrenceTransforms:changes=>{for(const c of changes)transforms.set(c.pathId,[...c.transform]);return true;}};
 const viewer={getOccurrenceIdManager:()=>({getIdForName:path=>path==='part'?1:-1}),getOccurrenceDataManager:()=>({getOccurrenceTransform:()=>transforms.get('part')}),getModelViewManagers:()=>({getManager:()=>manager}),getCamera:()=>camera,draw:()=>{}};
 const controller={connection:{isClosed:()=>closed},getActiveElementTabId:()=>target.eid,getViewer:()=>viewer,
  documentModel:{get:k=>k==='microversionId'?{theId:revision}:{get:()=>'',definition:{assemblyTree:tree}}},
  elementConnection:{callAndPromise:async message=>{
   sent.push(message);
   if(message.getMessageName().endsWith('AnimateMateRequest'))return {errorCode:0,frames};
   for(const call of message.featureOccurrenceVisibilityCalls)for(const ref of call.features){
    const item=items.find(i=>i.getFeatureId()===ref.featureId&&JSON.stringify(i.getOccurrence().path)===JSON.stringify(ref.occurrence.path));item.treeNode.hidden=call.visibility===1;
   }
   return {};
  }}};
 const modules={27940:classes,3392:{GI:{getOpenDocumentController:()=>controller}},64725:{V:{itemsByPath:new Map(items.map((v,i)=>[String(i),v]))}}};
 const chunks=[];chunks.push=value=>{Array.prototype.push.call(chunks,value);value[2](id=>modules[id]);};globalThis.webpackChunkNewton=chunks;
 return {sent,connector,mate,transforms,setRevision:v=>revision=v,setClosed:v=>closed=v};
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
