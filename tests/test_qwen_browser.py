import os, json, queue, subprocess, sys, threading, time
os.environ['QT_QPA_PLATFORM']='offscreen'
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.backend.deepseek_adapter import BackendError, Cancelled
from app.backend.qwen_browser_transport import QwenBrowserAdapter
from app.backend.qwen_protocol import QwenVerificationRequired, LineSplitter, QwenStreamState
import app.ui.main_window as mw

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def sse(obj): return 'data: '+json.dumps(obj)+'\n\n'

class FakeBridge:
    """Scripted stand-in for the GUI-thread QwenBrowser bridge."""
    def __init__(self, script):
        self.script=script; self.specs=[]; self.aborted=[]
    def submit(self, spec):
        self.specs.append(spec); q=queue.Queue(); rid='r%d'%len(self.specs)
        for event in self.script(spec, len(self.specs)): q.put(event)
        return rid, q
    def abort(self, rid): self.aborted.append(rid)

def meta(status=200, ctype='application/json'): return {'kind':'meta','status':status,'ctype':ctype}
def data(text): return {'kind':'data','text':text}
END={'kind':'end'}

def json_reply(obj, status=200): return [meta(status), data(json.dumps(obj)), END]

def chat_stream(rid, text='Hello'):
    whole=sse({'response.created':{'chat_id':'c1','response_id':rid}})+sse({'choices':[{'delta':{'phase':'answer','content':text,'status':'typing'}}]})+sse({'choices':[{'delta':{'phase':'answer','content':'','status':'finished'},'finish_reason':'stop'}]})
    # split at awkward places, including inside JSON and between \r\n
    pieces=[whole[i:i+17] for i in range(0,len(whole),17)]
    return [meta(200,'text/event-stream; charset=utf-8')]+[data(p) for p in pieces]+[END]

def test_line_splitter_reassembles_lines():
    s=LineSplitter(); out=s.feed('data: {"a"')+s.feed(':1}\r\n\ndata: x')+s.flush()
    assert out==['data: {"a":1}','','data: x']

def test_create_session_spec_has_no_token_unless_override():
    bridge=FakeBridge(lambda spec,n: json_reply({'success':True,'data':{'id':'chat-1'}}))
    assert QwenBrowserAdapter(bridge,model='qwen3.8-max').create_session()=='chat-1'
    spec=bridge.specs[0]
    assert spec['method']=='POST' and spec['url']=='https://chat.qwen.ai/api/v2/chats/new' and spec['stream'] is False
    assert spec['token']=='' and 'authorization' not in {k.lower() for k in spec['headers']}
    assert json.loads(spec['body'])['models']==['qwen3.8-max']
    assert not any(k.lower() in ('cookie','bx-ua','bx-umidtoken') for k in spec['headers'])
    QwenBrowserAdapter(bridge,token='"Bearer manual"').create_session()
    assert bridge.specs[1]['token']=='manual'

def test_stream_multiturn_with_split_chunks(tmp_path):
    def script(spec,n):
        if spec['url'].endswith('/chats/new'): return json_reply({'success':True,'data':{'id':'c1'}})
        return chat_stream(f'resp-{n-1}','OK')
    bridge=FakeBridge(script); api=QwenBrowserAdapter(bridge)
    db=Storage(tmp_path/'h.db'); cid=db.create(provider='qwen'); db.execute('UPDATE conversations SET remote_id=? WHERE id=?',(api.create_session(),cid))
    for turn in range(3):
        if turn==1: db.db.close(); db=Storage(tmp_path/'h.db')
        row=db.conversations()[0]
        parts=list(api.stream(row['remote_id'],f'p{turn}',row['parent_id']))
        assert [(p['type'],p['content']) for p in parts]==[('text','OK'),('complete','')]
        db.execute('UPDATE conversations SET parent_id=? WHERE id=?',(parts[-1]['message_id'],cid))
    bodies=[json.loads(s['body']) for s in bridge.specs[1:]]
    assert [b['parent_id'] for b in bodies]==[None,'resp-1','resp-2']
    assert all(s['stream'] and s['url'].endswith('?chat_id=c1') for s in bridge.specs[1:])
    db.db.close()

@pytest.mark.parametrize('events,exc,match',[
    ([meta(401),data('{"error":"Your session has expired"}'),END],QwenVerificationRequired,'invalid or expired'),
    ([meta(200,'text/html'),data('<!doctype html><meta name="aliyun_waf_aa" content="x">'),END],QwenVerificationRequired,'web firewall'),
    (json_reply({'ret':['RGV587_ERROR::SM'],'data':{}}),QwenVerificationRequired,'web firewall'),
    ([meta(405,'text/html'),data('<html>Qwen is not available in your region.</html>'),END],BackendError,'not available in your region'),
    ([meta(429),data('{}'),END],BackendError,'rate limit'),
    ([{'kind':'error','error':'NO_TOKEN'}],QwenVerificationRequired,'Not logged in'),
    ([{'kind':'error','error':'NETWORK'}],QwenVerificationRequired,'could not reach'),
    ([{'kind':'error','error':'PAGE_RELOADED'}],QwenVerificationRequired,'reloaded'),
    ([{'kind':'error','error':'NOT_ON_SITE'}],QwenVerificationRequired,'not on chat.qwen.ai'),
    ([{'kind':'error','error':'LOAD_FAILED'}],QwenVerificationRequired,'could not load'),
])
def test_errors_map_to_verification_or_backend(events,exc,match):
    bridge=FakeBridge(lambda spec,n: events)
    with pytest.raises(exc,match=match) as info: QwenBrowserAdapter(bridge).create_session()
    if exc is BackendError: assert not isinstance(info.value,QwenVerificationRequired)
    assert len(bridge.specs)==1  # never retried automatically

@pytest.mark.parametrize('events,match',[
    ([meta(200,'text/event-stream'),data(sse({'error':{'code':'RateLimited','details':'x'}})),END],'rate limit'),
    ([meta(200,'text/event-stream'),data(sse({'response.created':{'response_id':'r'}})),END],'without an answer'),
    ([meta(200,'application/json'),data('{"success":false,"data":{"code":"Bad_Request"}}'),END],'rejected the request.*Bad_Request'),
    ([meta(200,'text/event-stream'),data('data: {broken\n'),END],'Invalid Qwen streaming'),
])
def test_stream_errors_are_reported(events,match):
    with pytest.raises(BackendError,match=match): list(QwenBrowserAdapter(FakeBridge(lambda s,n: events)).stream('c1','hi'))

def test_timeout_without_response_asks_for_verification_and_aborts():
    bridge=FakeBridge(lambda s,n: [])
    with pytest.raises(QwenVerificationRequired,match='No response from Qwen'): QwenBrowserAdapter(bridge,timeout=0.2).create_session()
    assert bridge.aborted==['r1']

def test_cancel_mid_stream_aborts_in_page_fetch():
    cancel=threading.Event()
    bridge=FakeBridge(lambda s,n: [meta(200,'text/event-stream'),data(sse({'response.created':{'response_id':'r'}})+sse({'choices':[{'delta':{'phase':'answer','content':'a'}}]}))])
    api=QwenBrowserAdapter(bridge,timeout=5,cancel=cancel); got=[]
    with pytest.raises(Cancelled):
        for p in api.stream('c1','hi'): got.append(p['content']); cancel.set()
    assert got==['a'] and set(bridge.aborted)=={'r1'}

def test_missing_bridge_is_reported():
    with pytest.raises(BackendError,match='QtWebEngine'): QwenBrowserAdapter(None)

def run_worker(worker):
    loop=QEventLoop(); worker.done.connect(loop.quit); worker.start(); QTimer.singleShot(5000,loop.quit); loop.exec(); worker.wait(2000)

def test_worker_uses_browser_transport_and_emits_verify(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'w.db'); cid=store.create(provider='qwen'); uid=store.add(cid,'user','hello','pending'); store.db.close()
    bridge=FakeBridge(lambda s,n: [meta(200,'text/html'),data('<meta name="aliyun_waf_aa">'),END])
    options=dict(timeout=5,thinking=False,search=False,streaming=True,auto_continue=True,qwen_transport='browser')
    w=mw.Worker('',None,None,'hello',options,tmp_path/'w.db',cid,user_id=uid,provider='qwen',bridge=bridge)
    verify=[]; failed=[]; w.verify.connect(verify.append); w.failed.connect(failed.append); run_worker(w)
    assert len(verify)==1 and not failed and 'کپچا' in verify[0]
    assert bridge.specs[0]['url'].endswith('/api/v2/chats/new')
    store=Storage(tmp_path/'w.db'); assert store.messages(cid)[0]['status']=='failed'; store.db.close()

def test_worker_browser_success(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'s.db'); cid=store.create(provider='qwen'); uid=store.add(cid,'user','hello','pending'); store.db.close()
    def script(spec,n):
        if spec['url'].endswith('/chats/new'): return json_reply({'success':True,'data':{'id':'c1'}})
        return chat_stream('resp-1','Hi there')
    bridge=FakeBridge(script)
    options=dict(timeout=5,thinking=False,search=False,streaming=True,auto_continue=True)
    run_worker(mw.Worker('',None,None,'hello',options,tmp_path/'s.db',cid,user_id=uid,provider='qwen',bridge=bridge))
    store=Storage(tmp_path/'s.db'); row=store.conversations()[0]; msgs=store.messages(cid)
    assert (row['remote_id'],row['parent_id'],row['pending_id'])==('c1','resp-1',None)
    assert [m['status'] for m in msgs]==['sent','sent'] and msgs[1]['content']=='Hi there'
    store.db.close()

def test_worker_http_transport_still_available(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'h.db'); cid=store.create(provider='qwen'); uid=store.add(cid,'user','hello','pending'); store.db.close()
    used=[]
    class FakeHttp:
        def __init__(self,*a): used.append('http')
        def create_session(self): raise BackendError('Qwen rate limit reached. Wait before retrying.')
    monkeypatch.setattr('app.ui.main_window.QwenAdapter',FakeHttp)
    options=dict(timeout=5,thinking=False,search=False,streaming=True,auto_continue=True,qwen_transport='http')
    failed=[]; w=mw.Worker('tok',None,None,'hello',options,tmp_path/'h.db',cid,user_id=uid,provider='qwen'); w.failed.connect(failed.append); run_worker(w)
    assert used==['http'] and failed

def test_token_required_rules():
    assert mw.token_required('deepseek',{}) and mw.token_required('deepseek',{'qwen_transport':'browser'})
    assert not mw.token_required('qwen',{}) and not mw.token_required('qwen',{'qwen_transport':'browser'})
    assert mw.token_required('qwen',{'qwen_transport':'http'})

class FakeVault:
    data={}
    def get_password(self,service,user): return self.data.get((service,user))
    def set_password(self,service,user,value): self.data[(service,user)]=value
    def delete_password(self,service,user): self.data.pop((service,user))

def test_settings_has_browser_transport(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    FakeVault.data={}; monkeypatch.setattr('app.ui.main_window.WinVaultKeyring',FakeVault)
    store=Storage(tmp_path/'t.db'); window=mw.Window(store); assert store.settings()['qwen_transport']=='browser'
    dialog=mw.Settings(window,store.settings())
    assert dialog.qwen_transport.currentData()=='browser' and dialog.qwen_browser_button.text()=='ورود / تأیید Qwen در مرورگر داخلی'
    dialog.provider.setCurrentIndex(1); dialog.save()
    assert dialog.values['provider']=='qwen' and dialog.values['qwen_transport']=='browser' and FakeVault.data=={}
    window.close(); store.db.close()

def test_persian_messages_for_browser_errors():
    assert 'مرورگر داخلی' in mw.persian_error('Not logged in to Qwen in the built-in browser','qwen')
    assert 'کپچا' in mw.persian_error('Qwen web firewall (Alibaba WAF) verification required','qwen')
    assert 'دوباره وارد' in mw.persian_error('Your Qwen session token is invalid or expired. Log in again in the built-in browser','qwen')

def test_real_webengine_bridge_against_local_server():
    """Runs QtWebEngine for real (separate process) against a fake local Qwen server."""
    env=dict(os.environ); env['QT_QPA_PLATFORM']='offscreen'; env['QTWEBENGINE_CHROMIUM_FLAGS']='--disable-gpu'
    proc=subprocess.run([sys.executable,os.path.join(ROOT,'tests','webengine_bridge_check.py')],cwd=ROOT,env=env,capture_output=True,text=True,timeout=150)
    lines=[l for l in proc.stdout.splitlines() if l.startswith('RESULT=')]
    assert lines, proc.stdout[-2000:]+proc.stderr[-2000:]
    result=json.loads(lines[-1][7:])
    if 'unavailable' in result: pytest.skip('QtWebEngine unavailable: '+result['unavailable'])
    assert 'exception' not in result and not result.get('timeout'), result
    assert result['load_ok'] is True and result['models']==['m1'] and result['chat']=='chat-1'
    assert ''.join(p[1] for p in result['turn1'])=='Hello' and result['turn1'][-1]==['complete','','resp-1']
    assert result['turn2_text']=='Hello'
    assert result['waf'].startswith('verification') and result['expired'].startswith('verification') and result['no_token'].startswith('verification')
    assert result['cancel']=='cancelled:first' and result['server_saw_abort'] is True
    assert result['overlay'].startswith('verification:Qwen web firewall verification (slider)') and result['overlay_seconds'] < 11, result
    assert result['seen']['cookie_sent'] is True
    assert 'unauthorized' in result['expired'] and 'Token has expired' in result['expired']
    assert set(result['seen']['auth'])=={'Bearer page-token','Bearer expired','Bearer FRESH'}  # never the manual override while the page has a token, never the stale token
    assert result['refreshed_chat']=='chat-1' and result['seen']['last_auth_fresh'] is True
    assert result['seen']['parents'][:2]==[None,'resp-1']
