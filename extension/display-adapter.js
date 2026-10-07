// Runs in Onshape's MAIN world. Only bounded, typed operations are accepted;
// callers cannot supply JavaScript. Runtime methods researched in display-research.md.
export async function displayCommand(job) {
  try {
    const {target, operation, args = {}} = job;
    const path = `/documents/${target.did}/w/${target.wid}/e/${target.eid}`;
    if (location.origin !== 'https://cad.onshape.com' || location.pathname !== path || new URLSearchParams(location.search).has('configuration'))
      throw new Error('Display target navigated or is configured. Use the exact unconfigured workspace tab.');
    let req;
    const chunks = globalThis.webpackChunkNewton;
    if (!chunks) throw new Error('Onshape runtime unavailable.');
    chunks.push([[`onshape_native_display_${crypto.randomUUID()}`], {}, r => {req = r;}]); chunks.pop();
    const types = req(27940), controller = req(3392).GI.getOpenDocumentController();
    if (controller?.getActiveElementTabId() !== target.eid) throw new Error('Active editor differs from target.');
    const model = controller.documentModel.get('activeElement');
    const micro = () => {const v = controller.documentModel.get('microversionId'); return typeof v === 'string' ? v : v?.theId;};
    const viewer = controller.getViewer();
    const manager = viewer?.getModelViewManagers()?.getManager();
    const before = micro();
    const connected = () => controller.connection?.isClosed?.() === false;
    const assertRevision = () => {
      if (!connected()) throw new Error('Onshape editor is disconnected. Reconnect that tab before writing; no command was sent.');
      if (controller.__onshapeNativePendingDisplayRpc?.pending) throw new Error('A previous display RPC is still pending. Inspect state or reload the saved element; do not replay it.');
      if (job.expected_microversion !== micro()) throw new Error('Display revision changed. Read fresh display_state.');
      if (model.get('idEditingFeature')) throw new Error('Finish the open feature edit before changing display or previewing motion.');
    };
    const constructors = new Map();
    for (const Type of Object.values(types)) if (typeof Type === 'function') {
      try {const name = Type.prototype?.getMessageName?.(); if (name) constructors.set(name, Type);} catch {}
    }
    const make = (name, values = {}) => {
      const Type = constructors.get(name); if (!Type) throw new Error(`Unsupported Onshape build: missing ${name}`);
      return Object.assign(new Type(), values);
    };
    const occurrence = path => make('assembly.GBTOccurrence', {path: [...path]});
    const call = async message => {
      const pending={pending:true,command:message.getMessageName(),started_at:new Date().toISOString()};
      controller.__onshapeNativePendingDisplayRpc=pending;
      const response=Promise.resolve(controller.elementConnection.callAndPromise(message)).finally(()=>{pending.pending=false;});
      let timer;
      try {
        return await Promise.race([response,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Native RPC timed out; outcome unknown. Read display_state. Do not replay while rpc_pending is present.')),20000);})]);
      } finally {clearTimeout(timer);}
    };
    const equal = (a,b) => JSON.stringify(a) === JSON.stringify(b);
    const nodeMap = () => req(64725).V;
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
    const displayState = () => ({...getRows(), microversion:micro(), target, connected:connected(),
      motion:session && session.path===path ? {session_id:session.id,state:session.state,microversion:session.microversion} : null,
      rpc_pending:controller.__onshapeNativePendingDisplayRpc?.pending ? {...controller.__onshapeNativePendingDisplayRpc} : null,
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
    if (operation === 'camera') {
      if(args.action==='read') return {camera:cameraState(),microversion:micro()};
      assertRevision();
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
