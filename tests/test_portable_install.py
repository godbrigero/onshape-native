import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('portable_install',ROOT/'install.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_platform_destinations_are_device_relative():
    assert installer.data_home('darwin',{},Path('/example'))==Path('/example/Library/Application Support/OnshapeNative')
    assert installer.data_home('linux',{'XDG_DATA_HOME':'/chosen'},Path('/example'))==Path('/chosen/onshape-native')
    assert installer.data_home('win32',{'LOCALAPPDATA':'C:/Example'},Path('/example'))==Path('C:/Example/OnshapeNative')


def archive(extra=None):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('repo/scripts/configure.py','pass')
        z.writestr('repo/uv.lock','version = 1')
        for name,value in (extra or {}).items():z.writestr(name,value)
    stream.seek(0)
    return stream


def test_download_excludes_device_files(tmp_path):
    installer.unpack(archive({'repo/.mcp.json':'private','repo/extension/local-config.js':'secret',
                              'repo/.runtime/bridge.json':'secret','repo/install.py':'source'}),tmp_path)
    assert (tmp_path/'install.py').read_text()=='source'
    assert not (tmp_path/'.mcp.json').exists()
    assert not (tmp_path/'.runtime').exists()
    assert not (tmp_path/'extension/local-config.js').exists()


@pytest.mark.parametrize('name',['repo/../../escape','/absolute','repo/back\\slash','repo/C:/escape'])
def test_unsafe_archive_paths_are_rejected(tmp_path,name):
    with pytest.raises(ValueError):installer.unpack(archive({name:'bad'}),tmp_path)
    assert not (tmp_path/'scripts/configure.py').exists()


def test_setup_registers_selected_clients_and_preserves_spaced_paths(tmp_path):
    calls=[]
    source=tmp_path/'source with spaces';runtime=tmp_path/'private data'
    installer.setup(source,runtime,['codex','claude'],'uv',lambda cmd,**kw:calls.append((cmd,kw)))
    assert len(calls)==4
    assert calls[0][0][2:4]==['--project',str(source)]
    assert calls[1][0][1]==str(source/'scripts/configure.py')
    assert calls[2][0][1]==str(source/'scripts/install_local.py')
    assert calls[3][0][1]==str(source/'scripts/install_claude.py')
    assert all(c[0][-1]==str(runtime) for c in calls[1:])
    assert all(c[1]['check'] for c in calls)


def test_generic_does_not_register_any_client(tmp_path):
    calls=[]
    installer.setup(tmp_path,tmp_path/'runtime',['generic'],'uv',lambda cmd,**kw:calls.append(cmd))
    assert len(calls)==2


def test_existing_checkout_reuses_generated_pairing(tmp_path,monkeypatch):
    (tmp_path/'scripts').mkdir();(tmp_path/'scripts/configure.py').write_text('pass')
    private=tmp_path/'existing-private'
    (tmp_path/'.mcp.json').write_text(json.dumps({'mcpServers':{'onshape_native':{'env':{'ONSHAPE_NATIVE_RUNTIME':str(private)}}}}))
    monkeypatch.setattr(installer.shutil,'which',lambda name:'/tools/'+name)
    calls=[];monkeypatch.setattr(installer,'setup',lambda *args:calls.append(args))
    installer.main(['--client','generic','--source',str(tmp_path)])
    assert calls[0][1]==private


def test_unmanaged_destination_is_not_replaced(tmp_path,monkeypatch):
    monkeypatch.setattr(installer.shutil,'which',lambda name:'/tools/'+name)
    with pytest.raises(ValueError,match='not managed'):
        installer.main(['--client','generic','--directory',str(tmp_path)])


def test_remote_install_reuses_runtime_and_rolls_back_source_on_failure(tmp_path,monkeypatch):
    destination=tmp_path/'managed'
    destination.mkdir()
    runtime=tmp_path/'private'
    (destination/installer.MARKER).write_text(json.dumps({'runtime':str(runtime)}))
    (destination/'keep.txt').write_text('previous source')
    monkeypatch.setattr(installer.shutil,'which',lambda name:'/tools/'+name)
    monkeypatch.setattr(installer,'urlopen',lambda *a,**kw:archive())
    def fail(source,selected_runtime,*args):
        assert source==destination and selected_runtime==runtime
        assert (source/'scripts/configure.py').exists()
        raise ValueError('simulated setup failure')
    monkeypatch.setattr(installer,'setup',fail)
    with pytest.raises(ValueError,match='simulated'):
        installer.main(['--client','generic','--directory',str(destination)])
    assert (destination/'keep.txt').read_text()=='previous source'
