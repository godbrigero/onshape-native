// Read-only requests can run in the extension without an active CAD tab.
// Host permission is restricted to cad.onshape.com; never export cookies.
export async function restGet(job) {
  const url = new URL(job.path, 'https://cad.onshape.com');
  const decoded = decodeURIComponent(decodeURIComponent(job.path));
  if (url.origin !== 'https://cad.onshape.com' || !/^\/api\/(?:v\d+\/)?[a-zA-Z]/.test(job.path) || /\.\.|[\\?#\x00]/.test(decoded) || /\/(clientinfo|oauth|apikeys)(\/|$)/i.test(decoded)) throw new Error('Invalid API path.');
  for (const [key,value] of Object.entries(job.query || {})) {
    if (value == null) continue;
    for (const v of Array.isArray(value) ? value : [value]) url.searchParams.append(key,String(v));
  }
  const headers={Accept:job.accept || 'application/json'};
  for (const [key,value] of Object.entries(job.request_headers || {})) {
    if (!['if-none-match','range'].includes(key.toLowerCase()) || /[\r\n]/.test(value)) throw new Error('Unsupported header.');
    headers[key]=value;
  }
  // Fetch hides manual redirect headers even with host permission. Observe only
  // the Location of this extension's exact request; never collect cookie headers.
  let redirect;
  const observe = details => {
    if (details.url !== url.href || details.method !== 'GET' || details.initiator !== `chrome-extension://${chrome.runtime.id}`) return;
    if (details.statusCode >= 300 && details.statusCode < 400 && details.statusCode !== 304)
      redirect = details.responseHeaders?.find(h=>h.name.toLowerCase()==='location')?.value;
  };
  const observer = chrome.webRequest?.onHeadersReceived;
  observer?.addListener(observe,{urls:['https://cad.onshape.com/api/*']},['responseHeaders']);
  let response;
  try { response=await fetch(url,{method:'GET',credentials:'include',headers,redirect:'manual',signal:AbortSignal.timeout(45000)}); }
  finally { observer?.removeListener(observe); }
  if (response.type==='opaqueredirect') {
    if (!redirect) throw new Error('Browser hid the export redirect. Reload the reviewed extension with its Onshape-only webRequest permission to enable downloads.');
    return {status:307,download_redirect:new URL(redirect,url).href};
  }
  if (response.status>=300 && response.status<400 && response.status!==304) return {status:response.status,download_redirect:response.headers.get('location')};
  const response_headers=Object.fromEntries(['etag','content-disposition','content-range','retry-after','x-ratelimit-remaining'].filter(k=>response.headers.has(k)).map(k=>[k,response.headers.get(k)]));
  const reader=response.body?.getReader();const chunks=[];let length=0;
  if (reader) while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>64*1024*1024){await reader.cancel();throw new Error('Response exceeds 64 MiB.');}chunks.push(value);}
  const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  const contentType=response.headers.get('content-type') || '';
  if (response.status===304) return {status:304,body:null,response_headers};
  if (!length) return {status:response.status,body:{},response_headers};
  if (contentType.includes('json')) return {status:response.status,body:JSON.parse(new TextDecoder().decode(bytes)),response_headers};
  let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return {status:response.status,encoding:'base64',contentType,body:btoa(binary),response_headers};
}
