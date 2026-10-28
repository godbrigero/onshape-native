// Runs in Onshape's MAIN world. Only bounded, typed operations are accepted;
// callers cannot supply JavaScript. Runtime methods researched in display-research.md.
export async function displayCommand(job) {
  try {
    const {target, operation, args = {}} = job;
    const path = `/documents/${target.did}/w/${target.wid}/e/${target.eid}`;
    if (location.origin !== 'https://cad.onshape.com' || location.pathname !== path || new URLSearchParams(location.search).has('configuration'))
      throw new Error('Display target navigated or is configured. Use the exact unconfigured workspace tab.');
  // Verified profiles: original 1.221 trace and assets captured 2026-10-20.
  // Keep this bootstrap identical in both injected functions (no worker closures).
  let require;
  const chunks = globalThis.webpackChunkNewton;
  if (!Array.isArray(chunks)) throw new Error("Onshape webpack runtime unavailable; document may still be loading.");
  const marker = `onshape_native_${crypto.randomUUID()}`;
  chunks.push([[marker], {}, r => { require = r; }]);
  if (chunks.at(-1)?.[0]?.[0] === marker) chunks.pop();
  if (typeof require !== "function") throw new Error("Onshape webpack runtime is not initialized; wait for the editor.");
  const profiles = [
    {classes:96402, controller:87539, registry:49857, sidebar:65443},
    {classes:27940, controller:3392, registry:45867, sidebar:64725}
  ];
  let profile, classes, controllerType;
  const failures = [];
  for (const candidate of profiles) {
    // Never scan or execute arbitrary modules when a known profile fails.
    let types, accessor;
    try { types = require(candidate.classes); accessor = require(candidate.controller)?.GI; }
    catch { failures.push(`${candidate.controller}:module-unavailable`); continue; }
    if (typeof types?.CJP !== "function" || typeof types?.D0n !== "function") {
      failures.push(`${candidate.classes}:message-classes-missing`); continue;
    }
    if (typeof accessor?.getOpenDocumentController !== "function") {
      failures.push(`${candidate.controller}:controller-accessor-missing`); continue;
    }
    profile = candidate; classes = types; controllerType = accessor; break;
  }
  if (!profile) throw new Error(`Unsupported Onshape frontend build [runtime-bootstrap: ${failures.join(", ")}]. Re-capture DevTools evidence.`);
    const types = classes, controller = controllerType.getOpenDocumentController();
    if (controller?.getActiveElementTabId() !== target.eid) throw new Error('Active editor differs from target.');
    const model = controller.documentModel.get('activeElement');
    const documentMicro = () => {const v = controller.documentModel.get('microversionId'); return typeof v === 'string' ? v : v?.theId;};
    const micro = () => {
      const v = model?.getMicroversionId?.() ?? model?.get?.('microversionId');
      return (typeof v === 'string' ? v : v?.theId) || documentMicro();
    };
    const viewer = controller.getViewer();
    const manager = viewer?.getModelViewManagers()?.getManager();
    const before = micro();
    const connected = () => controller.connection?.isClosed?.() === false;
    const assertRevision = () => {
      if (!connected()) throw new Error('Onshape editor is disconnected. Reconnect that tab before writing; no command was sent.');
      if (controller.__onshapeNativePendingDisplayRpc?.pending) throw new Error('A previous display RPC is still pending. Inspect state or reload the saved element; do not replay it.');
      if(controller.__onshapeNativeIncompleteFeatureEdit||controller.__onshapeNativeIncompleteTransform) throw new Error('A native edit is incomplete. Inspect and reload the saved element before writing.');
      if (job.expected_microversion !== micro()) throw new Error('Display revision changed. Read fresh display_state.');
      if (model.get('idEditingFeature')) throw new Error('Finish the open feature edit before changing display or previewing motion.');
    };
    const constructors = new Map();
    for (const Type of [...Object.values(types),...Object.values(require(profile.registry)?.E15||{})]) if (typeof Type === 'function') {
      try {const name = Type.prototype?.getMessageName?.(); if (name) constructors.set(name, Type);} catch {}
    }
    const make = (name, values = {}) => {
      const Type = constructors.get(name); if (!Type) throw new Error(`Unsupported Onshape build: missing ${name}`);
      return Object.assign(new Type(), values);
    };
    const occurrence = path => make('assembly.GBTOccurrence', {path: [...path]});
    const call = async (message,connection=controller.elementConnection) => {
      if(controller.__onshapeNativePendingDisplayRpc?.pending) throw new Error('A native RPC is still pending. Inspect state before continuing.');
      const pending={pending:true,command:message.getMessageName(),started_at:new Date().toISOString()};
      controller.__onshapeNativePendingDisplayRpc=pending;
      const response=Promise.resolve(connection.callAndPromise(message)).finally(()=>{pending.pending=false;});
      let timer;
      try {
        return await Promise.race([response,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Native RPC timed out; outcome unknown. Read display_state. Do not replay while rpc_pending is present.')),20000);})]);
      } finally {clearTimeout(timer);}
    };
    const equal = (a,b) => {
      if(a===b) return true;
      if(a==null||b==null||typeof a!=="object"||typeof b!=="object"||Array.isArray(a)!==Array.isArray(b)) return false;
      const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));
    };
    const nodeMap = () => {
      const registry = require(profile.sidebar)?.V;
      if (!(registry?.itemsByPath instanceof Map)) throw new Error(`Unsupported Onshape frontend build [sidebar-registry-missing:${profile.sidebar}].`);
      return registry;
    };
    const getRows = () => {
      const tree = model.definition?.assemblyTree;
      if (!tree?.isValid || !(tree.pathToNodes instanceof Map)) throw new Error('Assembly display tree is not ready.');
      const models = new Map();
      for (const item of nodeMap().itemsByPath.values()) if (item.treeNode) models.set(item.treeNode, item);
      const rows = [], issues = [];
      for (const [tree_path, node] of tree.pathToNodes) {
        const item = models.get(node);
        const native_type = node.getMessageName();
        const common = {tree_path, native_type, name: node.displayName, feature_id: node.featureId || null,
          hidden: node.hidden, suppressed: node.suppressed, suppressed_by_parent: node.suppressedByParent,
          inherited_connector: node.partStudioMateConnector === true, implicit: node.implicit === true,
          parent_path: tree_path.slice(0, Math.max(0,tree_path.lastIndexOf('.'))), children_count: node.childrenCount};
        if (!tree_path || !item || !item.getCanBeHidden?.()) {
          rows.push({...common, reference:null, effective_visible:null, reason:!item?'No corresponding sidebar model':'Not individually hideable'});
          if (tree_path && !item) issues.push(`Unresolved sidebar model: ${tree_path}`);
          continue;
        }
        const occ = item.getOccurrence()?.path;
        const reference = item.isFeature || item.isFolder
          ? {kind:'feature', feature_id:item.getFeatureId(), occurrence_path:occ}
          : {kind:'occurrence', occurrence_path:occ};
        if (!Array.isArray(occ) || (reference.kind === 'feature' && !reference.feature_id)) throw new Error(`Incomplete native reference for ${tree_path}`);
        const visibility = item.getVisibility();
        rows.push({...common, reference, visibility, parent_hidden: item.isParentHidden === true,
          effective_visible: visibility === types.z_V.VISIBLE && !item.isParentHidden && !node.suppressed && !node.suppressedByParent,
          mate_type: node.mateType || null,
          visibility_source:'Onshape sidebar model visibility, parent visibility and suppression; excludes camera occlusion and temporary isolation'});
      }
      const counts = new Map(); for (const row of rows) if (row.tree_path) counts.set(row.parent_path,(counts.get(row.parent_path)||0)+1);
      for (const row of rows) if ((counts.get(row.tree_path)||0) !== row.children_count) issues.push(`Incomplete sidebar children: ${row.tree_path}`);
      return {rows, complete:issues.length===0, issues};
    };
    const refKey = ref => JSON.stringify([ref.kind,ref.occurrence_path,ref.feature_id || '']);
    const match = (rows, ref) => {
      const found = rows.filter(row => row.reference && refKey(row.reference) === refKey(ref));
      if (!found.length) throw new Error('Reference is absent from the loaded assembly sidebar. Refresh display_state.');
      return found;
    };
    const cameraState = () => {
      const camera = viewer?.getCamera();
      if (!camera) throw new Error('Viewer camera is unavailable.');
      return {frame:Array.from(camera.getFrame()), view_matrix:Array.from(camera.getViewMatrix()),
        viewport:Array.from(camera.getViewport()), perspective:!camera.isOrthographic(),
        extents:camera.isOrthographic()?Array.from(camera.getExtents()):null};
    };
    const displayState = () => ({...getRows(), microversion:micro(), document_microversion:documentMicro(), target, connected:connected(),
      motion:session && session.path===path ? {session_id:session.id,state:session.state,microversion:session.microversion} : null,
      rpc_pending:controller.__onshapeNativePendingDisplayRpc?.pending ? {...controller.__onshapeNativePendingDisplayRpc} : null,
      incomplete_transform:controller.__onshapeNativeIncompleteTransform || null,
      incomplete_feature_edit:controller.__onshapeNativeIncompleteFeatureEdit || null,
      camera:cameraState(), captured_at:new Date().toISOString(), scope:'This exact browser tab; display state is mutable independently of geometry revision.'});
    // A session holds native frame objects and baseline transforms only in this
    // document controller, so navigation/reload cannot replay them into another model.
    const sessionKey = '__onshapeNativeMotionV1';
    let session = controller[sessionKey];
    const assertSession = () => {
      if (!session || session.id !== args.session_id || session.path !== path) throw new Error('Motion session unavailable. Use the session_id returned by prepare in this tab.');
      if (session.microversion !== micro() || !connected()) {
        clearInterval(session.timer); session.timer = null;
        throw new Error('Model changed during preview. Refusing to overwrite newer transforms; reload the element to restore its current saved pose.');
      }
    };
    const motionStatus = () => {
      const expected=new Map(session.baseline);
      if(session.index!==null) for(const changed of session.frames[session.index].changedOccurrences)
        expected.set(changed.occurrence.getPathAsString(),Array.from(changed.transform.getGlMatrix()));
      session.poseVerified=verifyTransforms([...expected].map(([pathId,transform])=>({pathId,transform})));
      return {session_id:session.id, state:session.state, frame:session.index, frame_count:session.frames.length,
      angle_radians:session.index === null || !session.poseVerified ? null : session.frames[session.index].mateDofValue,
      angle_degrees:session.index === null || !session.poseVerified ? null : session.frames[session.index].mateDofValue*180/Math.PI,
      angle_source:'Onshape solver frame mateDofValue; null before a frame or after restore',
      pose_verified:session.poseVerified, error:session.error || null, microversion:micro(), preview_only:true};
    };
    const renderedTransform = pathId => {
      const id=viewer.getOccurrenceIdManager().getIdForName(pathId);
      if(id<0) throw new Error('Occurrence is missing from the renderer.');
      return Array.from(viewer.getOccurrenceDataManager().getOccurrenceTransform(id));
    };
    const verifyTransforms = changes => changes.every(c => {
      // batchUpdateOccurrenceTransforms deliberately restores the model's stored
      // transforms after updating the renderer. Read rendered data, not model data.
      const actual = renderedTransform(c.pathId);
      return actual.length === 16 && c.transform.every((v,i)=>Math.abs(actual[i]-v)<1e-6);
    });
    const stop = () => {clearInterval(session.timer); session.timer=null; session.state='stopped';};
    const applyFrame = index => {
      if (session.microversion !== micro() || !connected() || controller.getActiveElementTabId() !== target.eid || location.pathname !== path) {
        stop(); session.state='invalidated'; session.error='Model or target changed. Reload the current element before further preview.'; return false;
      }
      const frame = session.frames[index];
      const changes = [...session.baseline].map(([pathId, transform])=>({pathId, transform:[...transform]}));
      const byPath = new Map(changes.map(c=>[c.pathId,c]));
      for (const changed of frame.changedOccurrences) byPath.get(changed.occurrence.getPathAsString()).transform = Array.from(changed.transform.getGlMatrix());
      if (!manager.batchUpdateOccurrenceTransforms(changes)) throw new Error('Onshape could not apply preview transforms. Restore the session.');
      viewer.draw(); session.index=index; session.poseVerified=verifyTransforms(changes);
      if (!session.poseVerified) throw new Error('Preview transform readback differs from solver frame. Restore the session.');
      return true;
    };
    if (operation === 'inspect') return displayState();
    if (operation === 'visibility') {
      assertRevision();
      if(session && session.state!=='restored') throw new Error('Restore the motion preview before changing persistent visibility.');
      const initial=displayState();
      if (!initial.complete) throw new Error('Incomplete sidebar. Resolve its issues before changing visibility.');
      const changes=args.changes;
      if (!Array.isArray(changes)||changes.length<1||changes.length>100) throw new Error('Provide 1–100 visibility changes.');
      const keys=new Set();
      for (const change of changes) {
        if(typeof change.visible !== 'boolean') throw new Error('visible must be a boolean.');
        const key=refKey(change.reference); if(keys.has(key)) throw new Error('Duplicate visibility reference.');keys.add(key);
        match(initial.rows,change.reference);
      }
      // Compare the read state, not just the geometry microversion. No atomic lock is claimed.
      if (args.expected_state && !equal(args.expected_state, initial.rows.map(r=>[r.tree_path,r.visibility,r.parent_hidden,r.suppressed,r.suppressed_by_parent])))
        throw new Error('Display state changed. Read fresh display_state before writing.');
      const batch=make('ui.assembly.GBTUiBatchVisibilityChange',{elementId:target.eid,editDescription:'Set visibility through Onshape Native'});
      for(const visible of [false,true]) {
        const group=changes.filter(c=>c.visible===visible);
        const occs=group.filter(c=>c.reference.kind==='occurrence').map(c=>occurrence(c.reference.occurrence_path));
        const features=group.filter(c=>c.reference.kind==='feature').map(c=>make('assembly.GBTFeatureReference',{
          featureId:c.reference.feature_id,occurrence:occurrence(c.reference.occurrence_path)}));
        if(occs.length) batch.occurrenceVisibilityCalls.push(make('ui.assembly.GBTUiChangeOccurrenceVisibility',{elementId:target.eid,occurrences:occs,hidden:!visible}));
        if(features.length) batch.featureOccurrenceVisibilityCalls.push(make('ui.assembly.GBTUiSetFeatureOccurrenceVisibility',{
          elementId:target.eid,features,visibility:visible?types.z_V.VISIBLE:types.z_V.HIDDEN,handleFeatureForGroup:true}));
      }
      await call(batch);
      let after, checks;
      for(let attempt=0;attempt<20;attempt++) {
        after=displayState(); checks=changes.map(c=>({reference:c.reference,requested_visible:c.visible,
          observed:match(after.rows,c.reference).map(r=>({name:r.name,effective_visible:r.effective_visible,visibility:r.visibility,parent_hidden:r.parent_hidden,suppressed:r.suppressed||r.suppressed_by_parent})),
          verified:match(after.rows,c.reference).every(r=>r.effective_visible===c.visible)}));
        if(checks.every(c=>c.verified)) break;
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      return {verified:checks.every(c=>c.verified),checks,microversion_before:before,...after};
    }
    if (operation === 'feature') {
      if(!connected()) throw new Error('Onshape editor is disconnected.');
      if(!model.definition?.assemblyTree) throw new Error('Select an assembly editor.');
      const plain = (value,depth=0) => {
        if(depth>40) throw new Error('Native definition nesting exceeds limit.');
        if(typeof value==='number'&&!Number.isFinite(value)) return null;
        if(value==null||typeof value!=='object') return value;
        if(Array.isArray(value)) return value.map(v=>plain(v,depth+1));
        const out={};if(typeof value.getMessageName==='function') out.$type=value.getMessageName();
        for(const [k,v] of Object.entries(value)) if(!k.startsWith('_')&&v!=null&&typeof v!=='function') out[k]=plain(v,depth+1);
        return out;
      };
      const hydrate = (value,depth=0) => {
        if(depth>40) throw new Error('Native definition nesting exceeds limit.');
        if(value==null||typeof value!=='object') return value;
        if(Array.isArray(value)) return value.map(v=>hydrate(v,depth+1));
        const out=value.$type?make(value.$type):Object.create(null);
        for(const [k,v] of Object.entries(value)) {
          if(k==='$type') continue;
          if(['__proto__','prototype','constructor'].includes(k)||k.startsWith('_')||(value.$type&&!Object.hasOwn(out,k))) throw new Error('Invalid native definition field.');
          out[k]=hydrate(v,depth+1);
        }
        return out;
      };
      const read = async()=>{
        const result=await call(make('ui.assembly.GBTUiAssemblyTreeItemDefinitionRequest',
          {elementId:target.eid,nodeId:args.node_id,parentOccurrence:occurrence(args.parent_occurrence_path)}));
        if(!result?.node||result.error) throw new Error('Native feature definition unavailable.');
        return plain(result.node);
      };
      const definition=await read();
      if(args.action==='read') return {definition,microversion:micro(),node_id:args.node_id,parent_occurrence_path:args.parent_occurrence_path};
      assertRevision();
      if(controller.__onshapeNativeIncompleteFeatureEdit) throw new Error('A previous native feature edit is incomplete. Inspect the editor before continuing.');
      if(!equal(definition,plain(args.expected_definition))) throw new Error('Feature definition changed. Read a fresh feature snapshot.');
      // Only edit definitions owned by this assembly; inherited features are read-only here.
      if(args.parent_occurrence_path.length) throw new Error('Edit the owning assembly for an inherited feature.');
      const nodes=new Map();
      const visit=value=>{
        if(!value||typeof value!=='object') return;
        if(value.nodeId) {if(nodes.has(value.nodeId)&&value.$type!=='tree.GBTNodeReference') throw new Error('Ambiguous definition node ID.');if(value.$type!=='tree.GBTNodeReference') nodes.set(value.nodeId,value);}
        for(const v of Object.values(value)) visit(v);
      };visit(definition);
      const selected=new Set(args.patches.map(p=>p.node_id));
      const containsSelected=value=>value&&typeof value==='object'&&(selected.has(value.nodeId)||Object.values(value).some(containsSelected));
      for(const id of selected) if(Object.values(nodes.get(id)||{}).some(containsSelected)) throw new Error('Do not patch both an ancestor node and its descendant.');
      const changes=args.patches.map(patch=>{
        const node=nodes.get(patch.node_id);if(!node) throw new Error('Patch node is absent from this feature definition.');
        const updated={...node};
        for(const [key,value] of Object.entries(patch.fields)) {
          if(['nodeId','featureId','$type','parameterId','sourceParseTreeNodes'].includes(key)||!Object.hasOwn(node,key)) throw new Error('Patch must preserve native identity and known fields.');
          updated[key]=value;
        }
        return make('diff.GBTTreeEditChange',{oldNode:make('tree.GBTNodeReference',{nodeId:node.nodeId}),newNode:hydrate(updated)});
      });
      const begin=make('ui.GBTUiBeginEdit',{elementId:target.eid,nodeId:args.node_id,rollbackState:1});
      const specify=changes.map((featureChange,i)=>make('ui.GBTUiSpecifyFeature',{elementId:target.eid,featureNodeId:args.node_id,featureChange,sequenceId:i+1,selectionMicroversion:null,inContextEntitiesToAdd:null,editDescription:args.edit_description}));
      const commit=make('ui.GBTUiCommit',{elementId:target.eid,featureNodeId:args.node_id,editDescription:args.edit_description});
      controller.__onshapeNativeIncompleteFeatureEdit={node_id:args.node_id,stage:'begin'};
      for(const [i,message] of [begin,...specify,commit].entries()) {
        if(!connected()||controller.getActiveElementTabId()!==target.eid||location.pathname!==path) throw new Error('Editor target or connection changed during feature edit.');
        controller.__onshapeNativeIncompleteFeatureEdit.stage=i;
        const result=await call(message);
        if(result?.error||result?.errorCode||result?.errorEnum) throw new Error('Native feature edit rejected; inspect before continuing.');
      }
      delete controller.__onshapeNativeIncompleteFeatureEdit;
      const after=await read();nodes.clear();visit(after);
      const checks=args.patches.map(p=>({node_id:p.node_id,verified:Object.entries(p.fields).every(([k,v])=>equal(nodes.get(p.node_id)?.[k],v))}));
      return {definition:after,microversion:micro(),checks,verified:checks.every(c=>c.verified),node_id:args.node_id,parent_occurrence_path:args.parent_occurrence_path};
    }
    if (operation === 'measure') {
      let message;
      if (args.use_selection) {
        message=controller.getMeasurementAreaController()?.getMeasureCallForSelections();
        if (!message) throw new Error('Select measurable geometry in this exact editor tab first.');
      } else {
        message=make('ui.GBTUiMeasureCall');
        message.viewerId=viewer.getViewerId();
        message.measurementReference=null;message.customOriginCoordinateSystem=null;
        message.entityQueries=(args.entities||[]).map(entity=>make(
          entity.occurrence_path ? 'assembly.GBTMIndividualQueryWithOccurrence' : 'bsedit.GBTMIndividualQuery',
          {nodeId:crypto.randomUUID().replaceAll('-','').slice(0,16),deterministicIds:[entity.deterministic_id],...(entity.occurrence_path?{path:entity.occurrence_path}:{})}));
        message.pointPositions=(args.points_m||[]).map(v=>make('math.GBTVector3d',{x:v[0],y:v[1],z:v[2]}));
      }
      if (!connected()) throw new Error('Onshape editor is disconnected.');
      message.elementId=target.eid;
      const result=await call(message,controller.connection);
      return {result,measured:!result?.error&&Array.isArray(result?.measurements)&&result.measurements.length>0,microversion:micro(),source:'native-editor',units:'Native measurement response; preserve quantity/unit metadata. Input points are meters.'};
    }
    if (operation === 'transform') {
      assertRevision();
      if (session && !['restored','invalidated'].includes(session.state)) throw new Error('Restore the motion preview before moving parts.');
      if (model.get('isInMiddleOfDrag') || controller.__onshapeNativeIncompleteTransform) throw new Error('A drag is active or incomplete. Inspect and reload the saved element before another transform.');
      const rows=getRows();if(!rows.complete) throw new Error('Assembly tree is incomplete.');
      const paths=args.occurrence_paths;
      for (const p of paths) match(rows.rows,{kind:'occurrence',occurrence_path:p});
      const baseline=paths.map(p=>({path:p,transform:Array.from(manager.getOccurrenceTransform(occurrence(p)))}));
      if(baseline.some(b=>b.transform.length!==16||b.transform.some(v=>!Number.isFinite(v)))) throw new Error('Saved occurrence transforms unavailable.');
      const rotate=args.action==='rotate';
      const prefix='ui.assembly.drag.GBTUiAssembly';
      const vector=v=>make('math.GBTVector3d',{x:v[0],y:v[1],z:v[2]});
      // Construct the complete sequence before the first mutation.
      const start=make(prefix+(rotate?'RotationStart':'TranslationStart'),{elementId:target.eid,occurrences:paths.map(occurrence),measureDuringDragCall:null});
      if(rotate) {start.dragPoint=vector(args.origin_m);start.dragAxis=vector(args.axis);}
      const change=make(prefix+(rotate?'RotationChange':'TranslationChange'),{elementId:target.eid,sequenceId:1});
      if(rotate) change.angle=-args.angle_degrees*Math.PI/180;else change.translation=vector(args.translation_m);
      const end=make(prefix+'DragEnd',{elementId:target.eid,editDescription:args.edit_description});
      const expected=baseline.map(b=>{
        const t=b.transform.slice();
        if(rotate) {
          const [x,y,z]=args.axis,c=Math.cos(-change.angle),s=Math.sin(-change.angle),d=1-c;
          const r=[[c+x*x*d,x*y*d-z*s,x*z*d+y*s],[y*x*d+z*s,c+y*y*d,y*z*d-x*s],[z*x*d-y*s,z*y*d+x*s,c+z*z*d]];
          for(let col=0;col<4;col++) for(let row=0;row<3;row++)
            t[col*4+row]=r[row].reduce((sum,v,k)=>sum+v*(b.transform[col*4+k]-(col===3?args.origin_m[k]:0)),0)+(col===3?args.origin_m[row]:0);
        } else for(let k=0;k<3;k++) t[12+k]+=args.translation_m[k];
        return {path:b.path,transform:t};
      });
      controller.__onshapeNativeIncompleteTransform={stage:'start',baseline};
      for(const [stage,message] of [['start',start],['change',change],['end',end]]) {
        if(!connected()||controller.getActiveElementTabId()!==target.eid||location.pathname!==path) throw new Error('Editor target or connection changed during transform; outcome requires inspection.');
        controller.__onshapeNativeIncompleteTransform.stage=stage;
        const response=await call(message);
        if(response?.error||response?.errorCode||response?.errorEnum) throw new Error(`Native transform rejected at ${stage}; inspect the editor before continuing.`);
      }
      delete controller.__onshapeNativeIncompleteTransform;
      let checks;
      for(let attempt=0;attempt<20;attempt++) {
      checks=expected.map(e=>{
        const actual=Array.from(manager.getOccurrenceTransform(occurrence(e.path)));
        const saved_matches=actual.length===16&&actual.every((v,i)=>Math.abs(v-e.transform[i])<1e-6);
        return {occurrence_path:e.path,expected_transform:e.transform,actual_transform:actual,saved_matches,rendered_matches:verifyTransforms([{pathId:occurrence(e.path).getPathAsString(),transform:actual}])};
      });
      if(checks.every(c=>c.saved_matches&&c.rendered_matches)) break;
      await new Promise(resolve=>setTimeout(resolve,100));
      }
      return {microversion:micro(),baseline,checks,verified:checks.every(c=>c.saved_matches&&c.rendered_matches),
        scope:'Selected occurrences; mates and rigid groups may move additional parts or constrain the requested transform. No groups were suppressed.'};
    }
    if (operation === 'camera') {
      if(args.action==='read') return {camera:cameraState(),microversion:micro()};
      // Camera state belongs to this tab, not to the document's modeling revision.
      // Exact URL/element guards above still apply, including saved-camera ownership.
      if (!connected()) throw new Error('Onshape editor is disconnected. Reconnect before changing the camera.');
      const view=viewer.getPrimaryViewController();
      if(args.action==='save') {
        const saved={id:crypto.randomUUID(),path,camera:viewer.getCamera().clone()};
        controller.__onshapeNativeCameraV1=saved;
        return {camera:cameraState(),camera_id:saved.id,microversion:micro()};
      }
      if(args.action==='restore') {
        const saved=controller.__onshapeNativeCameraV1;
        if(!saved||saved.id!==args.camera_id||saved.path!==path) throw new Error('Camera save handle unavailable in this tab.');
        viewer.getCamera().copyFrom(saved.camera);
      } else if(args.action==='standard') {
        const names={front:'XZ',back:'XZback',left:'YZback',right:'YZ',top:'XY',bottom:'XYback',isometric:'Isometric'};
        if(!names[args.view]) throw new Error('Unknown standard view.');
        view.setStandardView(names[args.view]);
      } else if(args.action==='orientation') {
        const camera=viewer.getCamera();
        if(args.extents && !camera.isOrthographic()) throw new Error('Extents require an orthographic camera.');
        camera.setFrame(args.frame);
        if(args.extents) camera.setExtents(args.extents);
      }
      else if(args.action!=='fit' && args.action!=='zoom') throw new Error('Unknown camera action.');
      if(args.action==='fit'||args.action==='zoom'||args.fit===true) {
        let bounds=viewer.getFitBounds();
        if(args.action==='zoom') {
          const all=args.occurrence_paths.map(p=>manager.getOccurrenceBounds(occurrence(p)));
          if(!all.length||all.some(b=>!b?.isFinite())) throw new Error('Occurrence bounds unavailable. No zoom applied.');
          bounds=all[0].clone(); for(const b of all.slice(1)) bounds.addBox(b);
        }
        const fitted=view.getZoomFitTargetCamera(viewer.getCamera().getFrame(),bounds);
        viewer.getCamera().copyFrom(fitted);
      }
      view.updateCameraNearFar(); view.afterViewChange(); viewer.draw();
      return {camera:cameraState(),microversion:micro(),applied:true};
    }
    if(operation==='capture') {
      const gl=viewer?.getGlContext();
      if(!gl?.canvas?.width||!gl.canvas.height||gl.isContextLost()) throw new Error('Viewport is unavailable or WebGL context was lost.');
      // Read in the same JS task as draw, before the browser discards WebGL pixels.
      viewer.draw();
      const canvas=document.createElement('canvas');
      const scale=Math.min(1,(args.max_size||1600)/Math.max(gl.canvas.width,gl.canvas.height));
      canvas.width=Math.max(1,Math.round(gl.canvas.width*scale));canvas.height=Math.max(1,Math.round(gl.canvas.height*scale));
      const context=canvas.getContext('2d');context.drawImage(gl.canvas,0,0,canvas.width,canvas.height);
      const pixels=context.getImageData(0,0,canvas.width,canvas.height).data;
      let nonempty=false;for(let i=3;i<pixels.length;i+=4) if(pixels[i]) {nonempty=true;break;}
      if(!nonempty) throw new Error('Viewport readback was blank. No screenshot artifact was produced.');
      let background=null;
      for(let element=gl.canvas;element;element=element.parentElement) {
        const color=getComputedStyle(element).backgroundColor;
        if(color && color!=='transparent' && !/^rgba\([^)]*,\s*0\)$/.test(color)) {background=color;break;}
      }
      if(background) {context.globalCompositeOperation='destination-over';context.fillStyle=background;context.fillRect(0,0,canvas.width,canvas.height);}
      return {encoding:'base64',mime_type:'image/png',image:canvas.toDataURL('image/png').split(',')[1],width:canvas.width,height:canvas.height,
        camera:cameraState(),microversion:micro(),connected:connected(),background,captured_at:new Date().toISOString(),scope:'Current Onshape WebGL viewport, including its rendered markers and solid CSS background; excludes HTML sidebar/dialog overlays and CSS background images.'};
    }
    if(operation==='motion') {
      if(args.action==='prepare') {
        assertRevision();
        if(session && session.state!=='restored') throw new Error('Restore the existing motion session before preparing another.');
        const rows=getRows(); const matches=match(rows.rows,args.mate);
        if(matches.some(r=>r.mate_type!=='REVOLUTE'||r.suppressed||r.suppressed_by_parent)) throw new Error('Choose an unsuppressed revolute mate from display_state.');
        const message=make('assembly.GBTUiAssemblyAnimateMateRequest',{elementId:target.eid,editDescription:'Preview revolute mate'});
        message.mate.featureId=args.mate.feature_id;message.mate.path=[...args.mate.occurrence_path];message.mate.queryData='Rz';
        Object.assign(message.numFrames,{value:args.frames,expression:String(args.frames),isInteger:true});
        Object.assign(message.startValue,{value:args.start_degrees,expression:`${args.start_degrees} deg`,units:'degree'});
        Object.assign(message.endValue,{value:args.end_degrees,expression:`${args.end_degrees} deg`,units:'degree'});
        const response=await call(message);
        if(response.errorCode!==0||!response.frames?.length) throw new Error(`Animation solver failed: ${response.errorString||response.errorCode}`);
        if(micro()!==before) throw new Error('Model changed while solving preview. No frames applied.');
        const baseline=new Map();
        for(const frame of response.frames) for(const changed of frame.changedOccurrences) {
          if(!manager.hasGraphicsOccurrenceData(changed.occurrence)) throw new Error('Animation occurrence graphics are not loaded.');
          const key=changed.occurrence.getPathAsString();
          if(!baseline.has(key)) baseline.set(key,renderedTransform(key));
        }
        session={id:crypto.randomUUID(),path,microversion:before,frames:response.frames,baseline,index:null,state:'prepared',poseVerified:true,timer:null};
        controller[sessionKey]=session; return motionStatus();
      }
      assertSession();
      if(args.action==='status') return motionStatus();
      if(args.action==='stop') {stop();return motionStatus();}
      if(args.action==='restore') {
        stop();const changes=[...session.baseline].map(([pathId,transform])=>({pathId,transform}));
        const applied=manager.batchUpdateOccurrenceTransforms(changes);viewer.draw();session.poseVerified=applied&&verifyTransforms(changes);
        session.state=session.poseVerified?'restored':'restore_failed';if(session.poseVerified)session.index=null;
        return motionStatus();
      }
      if(args.action==='step') {
        stop();if(!Number.isInteger(args.frame)||args.frame<0||args.frame>=session.frames.length) throw new Error('Frame index outside computed animation.');
        applyFrame(args.frame);return motionStatus();
      }
      if(args.action==='start') {
        stop();session.state='playing';let next=session.index===null?0:(session.index+1)%session.frames.length;
        const tick=()=>{try{if(!applyFrame(next))return;next++;if(next>=session.frames.length)stop();}catch(error){stop();session.state='error';session.error=String(error.message);}};
        tick();if(session.state==='playing') session.timer=setInterval(tick,1000/args.fps);
        return motionStatus();
      }
      throw new Error('Unknown motion action.');
    }
    throw new Error('Unsupported display operation.');
  } catch(error) {return {error:String(error.message||error).slice(0,700),outcome:'Inspect state before retrying; mutations are never automatically replayed.'};}
}
