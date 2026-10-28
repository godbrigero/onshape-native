from copy import deepcopy
from types import SimpleNamespace

import pytest

from onshape_native.client import OnshapeError
from onshape_native.feature_studio import FeatureStudio, edited_source
from onshape_native.store import Store

URL='https://cad.onshape.com/documents/'+'a'*24+'/w/'+'b'*24+'/e/'+'c'*24
TARGET=dict(did='a'*24,wvm='w',wvmid='b'*24,eid='c'*24)
CODE='FeatureScript 3095;\n// original\n'


def fixture(tmp_path):
    raw=dict(contents=CODE,sourceMicroversion='d'*24,serializationVersion='1.2.23',libraryVersion=0)
    calls=[]
    async def call(operation,target,query=None,body=None):
        calls.append((operation,deepcopy(target),deepcopy(body)))
        if operation=='getFeatureStudioContents':return deepcopy(raw)
        if operation=='updateFeatureStudioContents':
            assert body['rejectMicroversionSkew'] is True
            assert body['sourceMicroversion']==raw['sourceMicroversion']
            raw.update(contents=body['contents'],sourceMicroversion='e'*24)
            return deepcopy(raw)
        if operation=='getFeatureStudioSpecs':return {'featureSpecs':[]}
        raise AssertionError(operation)
    s=SimpleNamespace(store=Store(tmp_path),locks={},call=call,target=lambda url:(dict(TARGET),''))
    return FeatureStudio(s),raw,calls


async def test_local_file_edit_preview_and_verified_save(tmp_path):
    fs,raw,calls=fixture(tmp_path)
    read=await fs.run(URL)
    from pathlib import Path
    local=Path(read['source_path']);assert local.read_text()==CODE
    local.write_text(CODE.replace('original','changed'))
    preview=await fs.run(URL,'edit',read['snapshot'],source_path=str(local),preview=True)
    assert preview['written'] is False and '+// changed' in preview['diff_preview']
    assert raw['contents']==CODE
    # Other tabs may change the document revision without altering this source.
    raw['sourceMicroversion']='f'*24
    result=await fs.run(URL,'edit',read['snapshot'],source_path=str(local))
    assert result['verified'] and result['written']
    assert result['check']['compilation_verified'] is False
    writes=[c for c in calls if c[0]=='updateFeatureStudioContents']
    assert len(writes)==1 and writes[0][2]['sourceMicroversion']=='f'*24
    assert calls[-1][1]['wvm']=='m' and calls[-1][1]['wvmid']=='e'*24
    assert fs.s.store.read(read['snapshot'])['raw']['contents']==CODE


async def test_concurrent_source_change_prevents_write(tmp_path):
    fs,raw,calls=fixture(tmp_path);read=await fs.run(URL)
    raw['contents']+='// collaborator\n'
    with pytest.raises(OnshapeError,match='changed since'):
        await fs.run(URL,'edit',read['snapshot'],patches=[{'old':'original','new':'ours'}])
    assert not any(c[0]=='updateFeatureStudioContents' for c in calls)


async def test_noop_and_wrong_target_never_write(tmp_path):
    fs,raw,calls=fixture(tmp_path);read=await fs.run(URL)
    result=await fs.run(URL,'edit',read['snapshot'],source=CODE)
    assert not result['written'] and not result['changed']
    fs.s.target=lambda url:({**TARGET,'eid':'f'*24},'')
    with pytest.raises(OnshapeError,match='exact target'):
        await fs.run(URL,'edit',read['snapshot'],source='different')
    assert not any(c[0]=='updateFeatureStudioContents' for c in calls)


@pytest.mark.parametrize('patches',[[{'old':'x','new':'y'}],[{'old':'a','new':'b'}],[{'old':'','new':'b'}],[{'old':'a','new':1}],[]])
def test_ambiguous_missing_and_malformed_patches_fail(patches):
    with pytest.raises(OnshapeError):edited_source('aaa',patches=patches)


def test_explicit_source_choice_and_file_validation(tmp_path):
    with pytest.raises(OnshapeError):edited_source(CODE,source='a',patches=[])
    with pytest.raises(OnshapeError):edited_source(CODE,source_path='relative.fs')
    p=tmp_path/'code.fs';p.write_bytes(b'\xff')
    with pytest.raises(OnshapeError,match='UTF-8'):edited_source(CODE,source_path=str(p))
    assert edited_source(CODE,patches=[{'old':'// original','new':'// changed'}])==CODE.replace('original','changed')


async def test_postwrite_read_failure_does_not_replay(tmp_path):
    fs,raw,calls=fixture(tmp_path);read=await fs.run(URL);original=fs.s.call
    async def failing(operation,*args,**kwargs):
        if operation=='getFeatureStudioContents' and raw['sourceMicroversion']=='e'*24:raise OnshapeError('offline')
        return await original(operation,*args,**kwargs)
    fs.s.call=failing
    result=await fs.run(URL,'edit',read['snapshot'],source=CODE+'// change\n')
    assert result['written'] and not result['verified']
    assert len([c for c in calls if c[0]=='updateFeatureStudioContents'])==1
