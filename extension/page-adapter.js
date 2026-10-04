// This function runs in Onshape's MAIN world. Only structured data crosses in.
// No credentials, executable source, or extension token are passed to the page.
export async function pageCommand(job) {
  "use strict";
  try {
  const MAX = 64 * 1024 * 1024;
  const target = job.target;
  if (location.origin !== "https://cad.onshape.com") throw new Error("Wrong origin.");
  if (target && location.pathname !== `/documents/${target.did}/w/${target.wid}/e/${target.eid}`) {
    throw new Error("Target tab navigated. Resolve its current state before retrying.");
  }
  if (target && new URLSearchParams(location.search).get("configuration")) throw new Error("Native editor commands require an unconfigured workspace tab. Use REST for configurations.");

  if (job.kind === "rest") {
    const decoded = decodeURIComponent(decodeURIComponent(job.path));
    if (!/^\/api\/(?:v\d+\/)?[a-zA-Z]/.test(job.path) || /\.\.|[\\?#\x00]/.test(decoded)) throw new Error("Invalid API path.");
    if (/\/(clientinfo|oauth|apikeys)(\/|$)/i.test(decoded) || (/\/users\/session\/?$/.test(decoded) && job.method !== "GET")) throw new Error("Authentication endpoint refused. Sign in through Onshape.");
    const url = new URL(job.path, location.origin);
    for (const [key, value] of Object.entries(job.query || {})) {
      if (value == null) continue;
      for (const v of Array.isArray(value) ? value : [value]) url.searchParams.append(key, String(v));
    }
    const headers = {Accept: job.accept || "application/json"};
    if (job.method !== "GET") headers["Content-Type"] = job.content_type || "application/json";
    if (Object.values(headers).some(v => /[\r\n]/.test(v))) throw new Error("Invalid media type.");
    for (const [key,value] of Object.entries(job.request_headers || {})) {
      if (!["if-none-match","range"].includes(key.toLowerCase()) || /[\r\n]/.test(value)) throw new Error("Unsupported request header.");
      headers[key] = value;
    }
    // Onshape's browser requests use this same cookie/header pair. Token stays here.
    const csrf = document.cookie.split(";").map(x => x.trim()).find(x => x.startsWith("XSRF-TOKEN="));
    if (csrf && job.method !== "GET") headers["X-XSRF-TOKEN"] = decodeURIComponent(csrf.slice("XSRF-TOKEN=".length));
    const response = await fetch(url, {method: job.method, headers, credentials: "same-origin",
      // GET export redirects carry no XSRF header or cross-origin cookies.
      redirect: job.method === "GET" ? "follow" : "error", signal: AbortSignal.timeout(45000),
      body: job.method === "GET" ? undefined : job.body_base64 != null
        ? Uint8Array.from(atob(job.body_base64), c => c.charCodeAt(0))
        : job.body == null && !job.body_present ? undefined : JSON.stringify(job.body)});
    const reader = response.body?.getReader();
    const chunks = []; let length = 0;
    if (reader) while (true) {
      const {done, value} = await reader.read(); if (done) break;
      length += value.length;
      if (length > MAX) { await reader.cancel(); throw new Error("Response exceeds 64 MiB; narrow the query."); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const contentType = response.headers.get("content-type") || "";
    const response_headers = Object.fromEntries(["etag","content-disposition","content-range","retry-after","x-ratelimit-remaining"]
      .filter(key=>response.headers.has(key)).map(key=>[key,response.headers.get(key)]));
    if (response.status === 304) return {status:304,body:null,response_headers};
    if (!length) return {status: response.status, body: {}, response_headers};
    if (contentType.includes("json")) return {status: response.status, body: JSON.parse(new TextDecoder().decode(bytes)), response_headers};
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return {status: response.status, encoding: "base64", contentType, body: btoa(binary), response_headers};
  }

  // These module IDs were recovered from the actual 1.221 DevTools trace.
  // Validate their shape every time and fail on incompatible frontend updates.
  let require;
  const chunks = globalThis.webpackChunkNewton;
  if (!Array.isArray(chunks)) throw new Error("Onshape webpack runtime unavailable; document may still be loading.");
  const marker = `onshape_native_${crypto.randomUUID()}`;
  chunks.push([[marker], {}, r => { require = r; }]);
  if (chunks.at(-1)?.[0]?.[0] === marker) chunks.pop();
  const classes = require?.(27940);
  const controllerType = require?.(3392)?.GI;
  if (!classes?.CJP || !classes?.D0n || typeof controllerType?.getOpenDocumentController !== "function") {
    throw new Error("Unsupported Onshape frontend build. Re-capture DevTools evidence before updating the adapter.");
  }
  const controller = controllerType.getOpenDocumentController();
  if (!controller || controller.getActiveElementTabId() !== target.eid) throw new Error("Target editor is not active or ready.");
  const documentModel = controller.documentModel;
  const elementModel = documentModel?.get("activeElement");
  const getMicroversion = () => {
    const value = documentModel?.get("microversionId");
    return typeof value === "string" ? value : value?.theId || "";
  };
  // The serializer registry includes nested types absent from the public barrel,
  // e.g. partstudio.GBTPSOIdentity in material and assembly insertion payloads.
  const registry = require?.(45867)?.E15;
  const constructors = new Map();
  for (const value of [...Object.values(classes), ...Object.values(registry || {})]) {
    if (typeof value !== "function" || typeof value.prototype?.getMessageName !== "function") continue;
    try { constructors.set(value.prototype.getMessageName(), value); } catch { /* not a message */ }
  }

  function plain(value, seen = new WeakSet(), depth = 0) {
    if (depth > 40) throw new Error("Response nesting exceeds limit.");
    if (value == null || typeof value !== "object") return value;
    if (seen.has(value)) throw new Error("Cyclic response refused.");
    seen.add(value);
    let output;
    if (value instanceof Map) output = {$map: [...value.entries()].map(([k,v]) => [plain(k, seen, depth + 1), plain(v, seen, depth + 1)])};
    else if (Array.isArray(value)) output = value.map(v => plain(v, seen, depth + 1));
    else if (ArrayBuffer.isView(value)) output = {typedArray: value.constructor.name, length: value.length};
    else {
      output = {};
      if (typeof value.getMessageName === "function") output.$type = value.getMessageName();
      for (const [key, item] of Object.entries(value)) {
        if (!key.startsWith("_") && typeof item !== "function") output[key] = plain(item, seen, depth + 1);
      }
    }
    seen.delete(value);
    return output;
  }
  function hydrate(value, depth = 0) {
    if (depth > 40) throw new Error("Command nesting exceeds limit.");
    if (value == null || typeof value !== "object") return value;
    if (Array.isArray(value)) return value.map(v => hydrate(v, depth + 1));
    let result = Object.create(null);
    if (value.$type) {
      const Type = constructors.get(value.$type);
      if (!Type) throw new Error(`Unknown native type: ${value.$type}`);
      result = new Type();
    }
    for (const [key, item] of Object.entries(value)) {
      if (key === "$type") continue;
      if (["__proto__", "constructor", "prototype"].includes(key) || key.startsWith("_")) throw new Error("Invalid native field.");
      if (value.$type && !Object.hasOwn(result, key)) throw new Error(`Unknown ${value.$type} field: ${key}`);
      result[key] = hydrate(item, depth + 1);
    }
    return result;
  }
  function bounded(value) {
    if (JSON.stringify(value).length > MAX) throw new Error("Native response exceeds 64 MiB.");
    return value;
  }
  function state() {
    const cache = controller.documentClientCache;
    const definition = elementModel?.definition;
    const root = definition?.assembly || cache?.getModelTreeState(target.eid)?.diffableModelTree?.getRoot();
    if (!root) throw new Error("Native model tree unavailable.");
    return bounded({target, microversion: getMicroversion(),
      editingFeatureId: elementModel?.get("idEditingFeature") || null,
      tree: plain(root),
      ...(definition?.assembly ? {assemblyTree: plain(definition.assemblyTree), computedData: plain(definition.computedData),
        assemblyTreeValid: definition.assemblyTree?.isValid === true,
        completeness: "Assembly definitions may be lazy. Use GBTUiAssemblyTreeItemDefinitionRequest or the full REST assembly for specific mate parameters."} : {}),
      revision_check: "client preflight only; not atomic against collaborators"});
  }
  if (job.kind === "state") return state();
  if (job.kind === "ui_inspect") {
    const nodes = [...document.querySelectorAll('button,input,select,textarea,[role="button"],[role="tab"],[role="menuitem"],[contenteditable="true"]')]
      .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== "hidden").slice(0, 500);
    const snapshot = crypto.randomUUID();
    globalThis.__onshapeNativeUI = {snapshot, nodes, pathname: location.pathname, created: Date.now()};
    return {snapshot, microversion: getMicroversion(), viewport: {width: innerWidth, height: innerHeight},
      controls: nodes.map((el, id) => ({id, tag: el.tagName.toLowerCase(), role: el.getAttribute("role"),
        label: (el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder") || el.textContent || "").trim().slice(0, 180),
        disabled: !!el.disabled, type: el.getAttribute("type")}))};
  }
  if (job.kind === "ui_action") {
    const saved = globalThis.__onshapeNativeUI;
    if (!saved || saved.snapshot !== job.snapshot || saved.pathname !== location.pathname || Date.now() - saved.created > 120000)
      throw new Error("UI snapshot expired. Inspect again before acting.");
    if (getMicroversion() !== job.expected_microversion) throw new Error("Native revision changed. Inspect again.");
    const el = saved.nodes[job.control];
    if (!el?.isConnected || !el.getClientRects().length || el.disabled) throw new Error("Control unavailable.");
    if (el.matches('input[type="password"],input[type="file"]')) throw new Error("Use API upload or the browser for this control.");
    delete globalThis.__onshapeNativeUI;
    el.focus();
    if (job.action === "click") el.click();
    else if (job.action === "double_click" || job.action === "context_menu")
      el.dispatchEvent(new MouseEvent(job.action === "double_click" ? "dblclick" : "contextmenu", {bubbles:true, cancelable:true, button:job.action === "context_menu" ? 2 : 0}));
    else if (job.action === "fill" || job.action === "select") {
      const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      if (!el.matches("input,textarea,select")) throw new Error("Control is not a form field.");
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, String(job.value ?? ""));
      el.dispatchEvent(new Event("input", {bubbles:true})); el.dispatchEvent(new Event("change", {bubbles:true}));
    } else throw new Error("Unsupported UI action.");
    return {dispatched:true, action:job.action, verification:"Inspect again; dispatch does not prove the application accepted a synthetic event."};
  }
  if (job.kind === "schema") {
    const Type = constructors.get(job.name);
    if (!Type) throw new Error("Unknown native message type.");
    return bounded({name: job.name, defaults: plain(new Type()), classId: new Type().getClassId()});
  }
  if (job.kind !== "native") throw new Error("Unknown page command.");
  // A second allowlist travels in the extension bundle, never supplied by HTTP callers.
  const allowed = new Set([
    "ui.GBTUiGetFeatureSettingsCall", "ui.GBTUiUpdateEditRollbackState", "ui.GBTUiAddFeatureCall",
    "ui.GBTUiBeginEdit", "ui.GBTUiCommit", "ui.GBTUiSetFeatureSettingsCall", "ui.GBTUiMeasureCall",
    "ui.GBTUiRenameFeature", "partstudiofolders.GBTUiCreateFolder",
    "ui.sketch.GBTUiSketchGetConstraintGraphCall", "ui.sketch.GBTUiSketchStartInferencing",
    "ui.sketch.GBTUiSketchFinishInferencing", "ui.sketch.GBTUiSketchChangeInferencingMode",
    "ui.sketch.GBTUiSketchAddRectangleCall", "ui.sketch.GBTUiSketchAddCircleCall",
    "ui.sketch.GBTUiSketchGetProjectionCall", "ui.sketch.GBTUiSketchAddDimensionCall",
    "ui.sketch.GBTUiSketchModifyDimensionCall"
  ]);
  const reads = new Set(["ui.GBTUiGetFeatureSettingsCall", "ui.GBTUiMeasureCall",
    "ui.sketch.GBTUiSketchGetConstraintGraphCall", "ui.sketch.GBTUiSketchGetProjectionCall",
    "ui.GBTUiMassPropCall", "ui.GBTUiGetQueryDataCall", "ui.document.GBTUiQueryInsertables",
    "ui.assembly.GBTUiAssemblyTreeItemDefinitionRequest"]);
  // Additional commands are allowed only when exported by the captured client
  // schema and present in the running serializer. Catalog labels them untested.
  if (!allowed.has(job.command) && (!job.command.includes("GBTUi") || !constructors.has(job.command) || /Response|Notification|DisplayData|ComputedData/.test(job.command))) {
    throw new Error("Native command is absent from the runtime schema.");
  }
  if (!reads.has(job.command) && (!job.expected_microversion || getMicroversion() !== job.expected_microversion)) {
    throw new Error("Native revision changed or unavailable. Read native_state before editing.");
  }
  if (job.body?.elementId && job.body.elementId !== target.eid) throw new Error("Body elementId differs from target.");
  const Type = constructors.get(job.command);
  if (!Type) throw new Error("Native command type unavailable.");
  const typedBody = {...job.body, $type: job.command};
  if (Object.hasOwn(new Type(), "elementId")) typedBody.elementId = target.eid;
  const message = hydrate(typedBody);
  // Captures use the constructor's empty messageId. The connection owns RPC
  // correlation; an invented UUID is not a documented editor message ID.
  if (Object.hasOwn(message, "messageId")) message.messageId = new Type().messageId;
  const before = getMicroversion();
  const connection = controller.elementConnection;
  if (typeof connection?.callAndPromise !== "function") throw new Error("Native editor connection unavailable.");
  // The editor allocates call IDs, serializes typed messages, and correlates replies.
  // Never replay captured bytes: their IDs and transaction state are session-specific.
  const result = await connection.callAndPromise(message);
  return bounded({result: plain(result), microversion_before: before, microversion_after: getMicroversion(),
    next: "Read native_state and check regeneration; an acknowledgement alone does not prove correct geometry."});
  } catch (error) {
    // Chrome discards a rejected executeScript promise's exception details.
    // Return a bounded diagnostic, never a stack or the request object.
    return {error: String(error?.message || error?.errorMessage || error?.getMessageName?.() || "Onshape page command rejected").slice(0,500),
      outcome: "Inspect current state before retrying a mutation."};
  }
}
