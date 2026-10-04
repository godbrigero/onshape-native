from onshape_native.templates import template


def test_template_preserves_parameter_types_but_drops_source_node_identity():
    spec={'featureType':'extrude','featureTypeName':'Extrude','parameters':[
        {'defaultValue':{'btType':'BTMParameterQuantity-147','nodeId':'stale','parameterId':'depth','expression':'25 mm','value':.025}},
        {'defaultValue':{'btType':'BTMParameterQueryList-148','parameterId':'entities','queries':[{'nodeId':'stale','queryString':'query=qEverything();'}]}}
    ]}
    output=template(spec)
    assert output['parameters'][0]['value']==.025
    assert 'nodeId' not in output['parameters'][0]
    assert 'nodeId' not in output['parameters'][1]['queries'][0]
    assert spec['parameters'][0]['defaultValue']['nodeId']=='stale'
