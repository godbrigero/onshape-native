"""Parse explicit MCP call records in a Markdown chat export, without executing it."""
from __future__ import annotations
import json
import re


def parse_thread(text):
    lines=[re.sub(r'^(?:> ?)+','',line) for line in text.splitlines()]
    starts=[];in_fence=False
    for index,line in enumerate(lines):
        if line.startswith('```'):in_fence=not in_fence
        elif not in_fence and line.strip()=='MCP tool call':starts.append(index)
    calls=[]
    for ordinal,start in enumerate(starts):
        end=starts[ordinal+1] if ordinal+1<len(starts) else len(lines)
        block=lines[start+1:end]
        nonempty=next((i for i,l in enumerate(block) if l.strip()),None)
        if nonempty is None:raise ValueError(f'Missing tool name at line {start+1}')
        name=block[nonempty].strip()
        if not re.fullmatch(r'[\w]+(?:[.][\w]+)+',name):raise ValueError(f'Invalid tool name at line {start+1}')
        fences=[];opened=None;language='';errors=[]
        for i,line in enumerate(block[nonempty+1:],nonempty+1):
            if line.startswith('```'):
                if opened is None:opened=i+1;language=line[3:].strip()
                else:fences.append((language,'\n'.join(block[opened:i])));opened=None
            elif opened is None:
                if line.startswith('Error:'):errors.append(line)
                if line.strip()=='</details>':break
        arguments=None;request_text=None;responses=[]
        for language,value in fences:
            if request_text is None and language=='json':
                request_text=value
                try:arguments=json.loads(value)
                except ValueError:pass
            elif request_text is not None and language=='text':responses.append(value)
        response='\n'.join(responses) if responses else ('\n'.join(errors) if errors else None)
        calls.append({'ordinal':ordinal+1,'line':start+1,'name':name,'arguments':arguments,
                      'request_text':request_text,'response':response,'error':bool(errors),
                      'image_output':any('Image output:' in l for l in block)})
    return calls


def variant(name,args):
    args=args or {};tool=name.split('.')[-1]
    if tool=='api_catalog':return 'schema:'+args['schema'] if args.get('schema') else 'search'
    if tool in ('api_read','api_write','api_upload'):return args.get('operation','unspecified')
    if tool=='artifact_page':
        pointer=args.get('pointer','')
        # Group paths; never export arbitrary IDs or user strings from pointers.
        match=re.match(r'^/([A-Za-z_]+)',pointer)
        return 'pointer:/'+match[1] if match else 'pointer:root/other'
    if tool=='inspect_model':return 'previous-snapshot' if args.get('previous') else 'full'
    if tool=='evaluate':return args.get('preset','summary')
    if tool in ('document_tree','element_tree'):return 'cached-page' if args.get('snapshot') else 'fresh'
    if tool in ('feature','sidebar_edit','document_edit'):return args.get('action','unspecified')
    if tool=='feature_template':return 'specific-type' if args.get('feature_type') else 'discover-types'
    return 'default'


def browser_intent(args):
    """Title-based proxies, not Onshape tool calls or guaranteed replacements."""
    title=(args or {}).get('title','').lower()
    for label,pattern in [
        ('motion',r'animat|playback|play |stop |rotation angle|spin.*lidar'),
        ('visibility',r'visib|hidden|hide |show |marker|connector|motor.*control|joint.*control'),
        ('camera',r'zoom|view cube|front view|isometric|fit.*view'),
        ('capture',r'screenshot|capture|snapshot'),
        ('hierarchy',r'folder|sidebar|feature.*list'),
    ]:
        if re.search(pattern,title):return label
    return 'other/ambiguous'
