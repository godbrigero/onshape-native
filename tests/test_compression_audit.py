"""Audit tests run with scripts/audit-requirements.txt; optional for runtime CI."""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

pytest.importorskip('tiktoken')
pytest.importorskip('matplotlib')
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('compression_audit',SCRIPTS/'compression_audit.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_expansion_counts_every_child_and_string_page():
    store=audit.MemoryStore()
    handle=store.put({'big':['x'*8000],'small':42})['artifact']
    cost=audit.expansion_cost(store,handle,'')
    # Root fallback, list fallback, two string pages and scalar read.
    assert cost['calls']==5
    assert cost['response_tokens']>audit.tokens('x'*8000)
    assert cost['argument_tokens']>0


def test_recovery_rejects_tampered_cache_and_incomplete_exports(tmp_path):
    original={'items':[1,2,3]}
    raw=audit.compact(original).encode()
    handle=hashlib.sha256(raw).hexdigest()+'.json'
    envelope={'data':original,'next_offset':None}
    assert audit.recover(tmp_path,handle,envelope)==(original,'complete exported value')
    assert audit.recover(tmp_path,handle,{'data':{'items':[1]},'next_offset':None})[0] is None
    (tmp_path/handle).write_text('{}')
    assert audit.recover(tmp_path,handle,envelope)==(None,'cache hash mismatch')


def test_replay_honors_requested_read_pointer_and_pagination(tmp_path):
    raw={'items':list(range(30))}
    payload=audit.compact(raw).encode();handle=hashlib.sha256(payload).hexdigest()+'.json'
    (tmp_path/handle).write_bytes(payload)
    result,source=audit.replay('api_read',{'pointer':'/items','offset':5,'limit':3},
                               {'artifact':handle},tmp_path,audit.MemoryStore())
    assert result['data']==[5,6,7] and result['next_offset']==8
    assert source=='verified cache'
