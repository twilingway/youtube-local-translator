"""Transport regressions from a real cold-load timeout after 30 minutes idle."""
import json
import httpx
from service.engine import Engine


def test_translation_and_rewrite_keep_model_resident_and_allow_cold_load():
    seen=[]
    def respond(request):
        seen.append((json.loads(request.content),request.extensions['timeout']))
        return httpx.Response(200,json={'message':{'content':'Я была рада.'}})
    engine=Engine.__new__(Engine)
    # A short default must not override the model's cold-load request budget.
    with httpx.Client(base_url='http://127.0.0.1:11439',transport=httpx.MockTransport(respond),timeout=20) as client:
        engine.http=client
        assert engine.translate('I was happy.','en','female')=='Я была рада.'
        assert engine.compact('Я была очень рада.',3,'female')=='Я была рада.'
    assert len(seen)==2
    for body,timeout in seen:
        assert body['keep_alive']==-1
        assert timeout['read']==180 and timeout['connect']==5
