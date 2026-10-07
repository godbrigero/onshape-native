#!/usr/bin/env python3
"""Read-only MCP protocol + optional model smoke test. Never mutates Onshape."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
async def main(url, config=None):
    if config:
        definition=json.loads(Path(config).read_text())['mcpServers']['onshape_native']
        params=StdioServerParameters(command=definition['command'],args=definition.get('args',[]),
                                    env={**os.environ,**definition.get('env',{})},cwd=definition.get('cwd'))
    else:
        params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'scripts/serve.py')],cwd=str(ROOT),env=os.environ.copy())
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools=(await session.list_tools()).tools
            assert len(tools)==35
            assert all(t.annotations is not None for t in tools)
            listing=await session.call_tool('api_catalog',{'search':'getAssemblyMassProperties'})
            assert not listing.isError
            assert json.loads(listing.content[0].text)['matches'][0]['operation']=='getAssemblyMassProperties'
            search=await session.call_tool('search_commands',{'task':'create a new assembly tab'})
            assert not search.isError
            matches=json.loads(search.content[0].text)['matches']
            assert len(matches)==10 and any(r['name']=='createAssembly' for r in matches)
            target=await session.call_tool('resolve_target',{'url':url or 'https://cad.onshape.com/documents/'+'a'*24+'/w/'+'b'*24+'/e/'+'c'*24})
            assert not target.isError and json.loads(target.content[0].text)['status']=='resolved'
            status=await session.call_tool('bridge_status',{})
            assert not status.isError
            connected=json.loads(status.content[0].text).get('extension_connected',False)
            print(json.dumps({'tools':len(tools),'schema_bytes':len(json.dumps([t.model_dump() for t in tools])),'extension_connected':connected}))
            if url:
                result=await session.call_tool('inspect_model',{'url':url})
                assert not result.isError
                data=json.loads(result.content[0].text)
                assert data['geometry_complete'] and not data['feature_errors']
                print(json.dumps({'microversion':data['microversion'],'features':data['feature_count'],'solids':len(data.get('solids',[]))}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url')
    parser.add_argument('--mcp-config',type=Path,help='Test the exact launcher generated for this device/client.')
    args=parser.parse_args()
    asyncio.run(main(args.url,args.mcp_config))
