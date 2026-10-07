import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('usage_audit',Path(__file__).parents[1]/'scripts/usage_audit.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_explicit_calls_not_mentions_or_examples_and_preserve_repeats():
    example='MCP tool call\n\nonshape_native.api_read\n\n```json\n{"operation":"read"}\n```\n\n```text\n{"data":1}\n```\n</details>\n'
    thread='Mention onshape_native.api_write.\n```text\nMCP tool call\nonshape_native.fake\n```\n'+example+''.join('> '+l+'\n' for l in example.splitlines())
    calls=module.parse_thread(thread)
    assert len(calls)==2 and calls[0]['name']==calls[1]['name']=='onshape_native.api_read'
    assert calls[1]['arguments']=={'operation':'read'}
    assert calls[1]['response']=='{"data":1}'

def test_error_empty_and_missing_responses_are_distinct():
    header='MCP tool call\n\nonshape_native.artifact_page\n\n```json\n{}\n```\n'
    calls=module.parse_thread(header+'Error: Invalid pointer\n</details>\n'+header+'```text\n\n```\n</details>\n'+header)
    assert calls[0]['error'] and calls[0]['response']=='Error: Invalid pointer'
    assert calls[1]['response']=='' and calls[2]['response'] is None

def test_arguments_do_not_become_frequencies_and_private_pointer_ids_stay_out():
    assert module.variant('onshape_native.artifact_page',{'pointer':'/rows/123/private-id'})=='pointer:/rows'
    assert module.browser_intent({'title':'Verify motor connector visibility'})=='visibility'
