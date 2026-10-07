#!/usr/bin/env python3
"""Portable setup: uv run --python 3.12 install.py --client codex|claude|generic."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote
from urllib.request import urlopen
import zipfile

# Public project coordinates, not a developer's filesystem or credentials.
REPOSITORY = 'godbrigero/onshape-native'
MARKER = '.onshape-native-source.json'


def data_home(platform=None, environ=None, home=None):
    platform = platform or sys.platform
    env = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == 'win32':
        return Path(env.get('LOCALAPPDATA', home / 'AppData/Local')) / 'OnshapeNative'
    if platform == 'darwin':
        return home / 'Library/Application Support/OnshapeNative'
    return Path(env.get('XDG_DATA_HOME', home / '.local/share')) / 'onshape-native'


def unpack(archive, destination):
    """Validate archive paths and extract source only, never local pairing."""
    with zipfile.ZipFile(archive) as bundle:
        members=[]
        for info in bundle.infolist():
            parts=PurePosixPath(info.filename).parts
            if not parts or '..' in parts or info.filename.startswith('/') or '\\' in info.filename:
                raise ValueError('Unsafe archive path')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Symlinks are not allowed in the source archive')
            if len(parts)<2 or info.is_dir():continue
            relative=Path(*parts[1:])
            if any(p in ('.git','.runtime','.venv','.env','.mcp.json','local-config.js','__pycache__') for p in relative.parts):continue
            if any(':' in p for p in relative.parts):raise ValueError('Unsafe archive path')
            members.append((info,relative))
        for info,relative in members:
            target=destination/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(bundle.read(info))
    if not (destination/'scripts/configure.py').is_file() or not (destination/'uv.lock').is_file():
        raise ValueError('Archive is not an Onshape Native source package')


def setup(source, runtime, clients, uv, run=subprocess.run):
    """All executable paths are computed on the destination device."""
    env={**os.environ,'UV_PROJECT_ENVIRONMENT':str(source/'.venv')}
    run([uv,'sync','--project',str(source),'--frozen','--no-dev','--python','3.12'],check=True,env=env)
    python=source/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    run([str(python),str(source/'scripts/configure.py'),'--runtime-dir',str(runtime)],check=True,env=env)
    for client in clients:
        script={'codex':'install_local.py','claude':'install_claude.py'}.get(client)
        if script:
            run([str(python),str(source/'scripts'/script),'--runtime-dir',str(runtime)],check=True,env=env)
    print('\nServer configured. Generated MCP configuration: '+str(source/'.mcp.json'))
    print('Browser step: open the extensions page, enable Developer mode, and Load unpacked: '+str(source/'extension'))
    print('Sign in to cad.onshape.com, then restart your AI client. No API keys are required.')
    if 'generic' in clients:
        print('Import the onshape_native entry from the generated .mcp.json into your client\'s stdio MCP settings.')
        print('Optional agent instructions: '+str(source/'skills/onshape-native-modeling/SKILL.md'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',choices=['codex','claude','both','generic'],required=True)
    parser.add_argument('--directory',type=Path,help='Destination for a downloaded source package.')
    parser.add_argument('--source',type=Path,help='Use an existing checkout instead of downloading.')
    parser.add_argument('--runtime-dir',type=Path,help='Private pairing/cache directory; keep the same value on updates.')
    parser.add_argument('--ref',default='main',help='Public GitHub branch, tag or commit to download.')
    args=parser.parse_args(argv)
    clients=['codex','claude'] if args.client=='both' else [args.client]
    uv=shutil.which('uv')
    if not uv:raise ValueError('Install uv first: https://docs.astral.sh/uv/getting-started/installation/')
    for client in clients:
        if client!='generic' and not shutil.which(client):
            raise ValueError(f'Install the {client} CLI and sign in first, or select --client generic.')
    local=Path(__file__).resolve().parent
    source=(args.source.expanduser().resolve() if args.source else
            local if (local/'scripts/configure.py').is_file() and not args.directory else None)
    runtime=(args.runtime_dir or data_home()/'runtime').expanduser().resolve()
    if source:
        if not (source/'scripts/configure.py').is_file():raise ValueError('Invalid --source checkout')
        # Existing configured checkouts retain their original pairing automatically.
        if not args.runtime_dir and (source/'.mcp.json').is_file():
            configured=json.loads((source/'.mcp.json').read_text())
            previous=configured.get('mcpServers',{}).get('onshape_native',{}).get('env',{}).get('ONSHAPE_NATIVE_RUNTIME')
            if previous:runtime=Path(previous).expanduser().resolve()
        setup(source,runtime,clients,uv)
        return
    destination=(args.directory or data_home()/'source').expanduser().absolute()
    if destination.is_symlink():raise ValueError('Refusing a symlinked destination')
    if destination.exists() and not (destination/MARKER).is_file():
        raise ValueError('Destination is not managed by this installer; use --source for a checkout or choose another --directory.')
    if destination==runtime or destination in runtime.parents:
        raise ValueError('Keep --runtime-dir outside the downloaded source directory.')
    if destination.exists() and not args.runtime_dir:
        marker=json.loads((destination/MARKER).read_text())
        runtime=Path(marker['runtime']).expanduser().resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.onshape-install-',dir=destination.parent) as temporary:
        stage=Path(temporary)/'source';stage.mkdir()
        url=f'https://codeload.github.com/{REPOSITORY}/zip/{quote(args.ref,safe="")}'
        print('Downloading public source: '+url,flush=True)
        with urlopen(url,timeout=60) as response:unpack(io.BytesIO(response.read()),stage)
        (stage/MARKER).write_text(json.dumps({'repository':REPOSITORY,'ref':args.ref,'runtime':str(runtime)}))
        backup=Path(temporary)/'previous'
        if destination.exists():destination.rename(backup)
        try:
            stage.rename(destination)
            setup(destination,runtime,clients,uv)
        except BaseException:
            if destination.exists():shutil.rmtree(destination)
            if backup.exists():backup.rename(destination)
            raise


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
