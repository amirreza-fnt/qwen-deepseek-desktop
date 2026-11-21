import os, json, threading, logging, time
os.environ['QT_QPA_PLATFORM']='offscreen'
import sqlite3
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.backend.deepseek_adapter import BackendError, Cancelled
from app.backend.qwen_adapter import QwenAdapter, QWEN_DEFAULT_MODEL
from app.backend.qwen_protocol import INLINE_CODE_INSTRUCTION, CONTINUE_PROMPT
import app.ui.main_window as mw

TOKEN='secret-qwen-token-123'

class Resp:
    def __init__(self, status=200, obj=None, lines=None, content_type=None, body=None):
        self.status_code=status; self.lines=lines or []
        if body is not None: self.content=body
        elif obj is not None: self.content=json.dumps(obj).encode()
        else: self.content=b''
        self.headers={'content-type': content_type or ('application/json' if obj is not None else 'text/event-stream')}
        self.closed=False
    def iter_lines(self): return iter(self.lines)
    def iter_content(self): yield self.content
    def close(self): self.closed=True

def sse(obj): return b'data: '+json.dumps(obj).encode()

def answer_lines(response_id, text, chat_id='chat-1'):
    return [sse({'response.created':{'chat_id':chat_id,'parent_id':None,'response_id':response_id}}),
            sse({'choices':[{'delta':{'role':'assistant','content':text,'phase':'answer','status':'typing'}}]}),
            sse({'choices':[{'delta':{'role':'assistant','content':'','phase':'answer','status':'finished'},'finish_reason':'stop'}]}),
            b'data: [DONE]']

def install(monkeypatch, handler):
    calls=[]
    def request(method,url,**kw):
        calls.append(dict(method=method,url=url,**kw)); return handler(method,url,kw)
    monkeypatch.setattr('app.backend.qwen_adapter.requests.request',request)
    return calls

def test_create_session_sends_bearer_and_returns_chat_id(monkeypatch):
    calls=install(monkeypatch,lambda m,u,kw: Resp(obj={'success':True,'data':{'id':'chat-1'}}))
    api=QwenAdapter('Bearer '+TOKEN,model='qwen3.8-max')
    assert api.create_session()=='chat-1'
    call=calls[0]
    assert call['method']=='POST' and call['url']=='https://chat.qwen.ai/api/v2/chats/new'
    assert call['headers']['authorization']=='Bearer '+TOKEN
    assert call['json']['models']==['qwen3.8-max'] and call['json']['chat_type']=='t2t'
    assert 'cookie' not in {k.lower() for k in call['headers']}

def test_stream_parses_thinking_and_answer(monkeypatch):
    lines=[sse({'response.created':{'chat_id':'chat-1','response_id':'resp-1'}}),
           sse({'choices':[{'delta':{'phase':'thinking_summary','content':'','extra':{'summary_thought':{'content':['Plan']}}}}]}),
           sse({'choices':[{'delta':{'phase':'thinking_summary','content':'','extra':{'summary_thought':{'content':['Plan step']}},'status':'finished'}}]}),
           b'',
           sse({'choices':[{'delta':{'phase':'answer','content':'Hello','status':'typing'}}]}),
           sse({'choices':[{'delta':{'phase':'answer','content':' world','status':'typing'}}]}),
           sse({'choices':[{'delta':{'phase':'answer','content':'','status':'finished'},'finish_reason':'stop'}]})]
    calls=install(monkeypatch,lambda m,u,kw: Resp(lines=lines))
    parts=list(QwenAdapter(TOKEN).stream('chat-1','Hi',thinking=True))
    assert [(p['type'],p['content']) for p in parts]==[('thinking','Plan'),('thinking',' step'),('text','Hello'),('text',' world'),('complete','')]
    assert all(p['message_id']=='resp-1' for p in parts)
    payload=calls[0]['json']
    assert calls[0]['url']=='https://chat.qwen.ai/api/v2/chat/completions?chat_id=chat-1'
    assert payload['stream'] is True and payload['incremental_output'] is True and payload['parent_id'] is None
    assert payload['model']==QWEN_DEFAULT_MODEL and payload['messages'][0]['content']==INLINE_CODE_INSTRUCTION+'\n\nHi'
    fc=payload['messages'][0]['feature_config']; assert fc['code_interpreter'] is False and fc['function_calling'] is False and fc['plugins_enabled'] is False
    assert payload['messages'][0]['feature_config']['thinking_enabled'] is True

def test_three_turns_chain_response_id_as_parent_across_restart(monkeypatch,tmp_path):
    seen=[]
    def handler(m,u,kw):
        if u.endswith('/chats/new'): return Resp(obj={'success':True,'data':{'id':'chat-9'}})
        seen.append(kw['json']); return Resp(lines=answer_lines(f'resp-{len(seen)}','OK','chat-9'))
    install(monkeypatch,handler)
    db=Storage(tmp_path/'history.db'); cid=db.create(provider='qwen'); api=QwenAdapter(TOKEN)
    db.execute('UPDATE conversations SET remote_id=? WHERE id=?',(api.create_session(),cid))
    for turn in range(3):
        if turn==1: db.db.close(); db=Storage(tmp_path/'history.db')
        row=db.conversations()[0]
        parts=list(api.stream(row['remote_id'],f'prompt {turn}',row['parent_id']))
        db.execute('UPDATE conversations SET parent_id=? WHERE id=?',(str(parts[-1]['message_id']),cid))
    assert [p['parent_id'] for p in seen]==[None,'resp-1','resp-2']
    assert [p['messages'][0]['parentId'] for p in seen]==[None,'resp-1','resp-2']
    assert all(p['chat_id']=='chat-9' for p in seen)
    assert db.conversations()[0]['provider']=='qwen'
    db.db.close()

@pytest.mark.parametrize('response,expected',[
    (Resp(401,obj={'error':'Your session has expired, or the token is no longer valid.'}),'invalid or expired'),
    (Resp(429,obj={}),'rate limit'),
    (Resp(200,obj={'success':False,'data':{'code':'RateLimited','details':'You have reached the limit'}}),'rate limit'),
    (Resp(200,obj={'success':False,'data':{'code':'Unauthorized','details':'invalid token'}}),'invalid or expired'),
    (Resp(200,obj={'ret':['FAIL_SYS_USER_VALIDATE::x'],'data':{}}),'web firewall'),
    (Resp(200,body=b'<!doctype html><meta name="aliyun_waf_aa" content="x">',content_type='text/html; charset=utf-8'),'web firewall'),
    (Resp(405,body=b'<html><title>Qwen</title>Qwen is not available in your region.</html>',content_type='text/html'),'not available in your region'),
    (Resp(403,obj={}),'Cloudflare'),
    (Resp(502,obj={}),'unavailable'),
    (Resp(200,obj={'success':True,'data':{}}),'no session ID'),
])
def test_session_errors_are_reported_not_invented(monkeypatch,response,expected):
    install(monkeypatch,lambda m,u,kw: response)
    with pytest.raises(BackendError,match=expected): QwenAdapter(TOKEN).create_session()
    assert response.closed

@pytest.mark.parametrize('lines,expected',[
    ([sse({'error':{'code':'RateLimited','details':'Too many requests'}})],'rate limit'),
    ([sse({'response.created':{'response_id':'r'}}),sse({'choices':[{'delta':{'phase':'answer','status':'error','content':''}}]})],'reported an error'),
    ([sse({'response.created':{'response_id':'r'}}),b'data: [DONE]'],'without an answer'),
    ([b'data: {not json'],'Invalid Qwen streaming'),
    ([b'<!doctype html>',b'<meta name="aliyun_waf_aa" content="x">'],'web firewall'),
])
def test_stream_errors(monkeypatch,lines,expected):
    install(monkeypatch,lambda m,u,kw: Resp(lines=lines))
    with pytest.raises(BackendError,match=expected): list(QwenAdapter(TOKEN).stream('chat-1','Hi'))

def test_json_reply_instead_of_stream_is_error(monkeypatch):
    install(monkeypatch,lambda m,u,kw: Resp(obj={'success':False,'data':{'code':'Bad_Request','details':'x'}}))
    with pytest.raises(BackendError,match='rejected the request.*Bad_Request: x'): list(QwenAdapter(TOKEN).stream('chat-1','Hi'))

def test_cancel_before_and_during_stream(monkeypatch):
    e=threading.Event(); e.set()
    with pytest.raises(Cancelled): QwenAdapter(TOKEN,cancel=e).create_session()
    e=threading.Event(); api=QwenAdapter(TOKEN,cancel=e)
    def lines():
        yield sse({'response.created':{'response_id':'r'}})
        yield sse({'choices':[{'delta':{'phase':'answer','content':'a'}}]})
        e.set()
        yield sse({'choices':[{'delta':{'phase':'answer','content':'b'}}]})
    r=Resp(); r.iter_lines=lines
    install(monkeypatch,lambda m,u,kw: r)
    got=[]
    with pytest.raises(Cancelled):
        for p in api.stream('chat-1','Hi'): got.append(p['content'])
    assert got==['a'] and r.closed

def test_no_automatic_retry_and_token_not_logged(monkeypatch,caplog):
    calls=install(monkeypatch,lambda m,u,kw: Resp(429,obj={'error':'limit'}))
    caplog.set_level(logging.INFO,logger='deepseek_desktop.backend')
    with pytest.raises(BackendError): list(QwenAdapter(TOKEN).stream('chat-1','Hi'))
    assert len(calls)==1
    assert TOKEN not in caplog.text and 'chat-1' not in caplog.text

def test_empty_token_rejected():
    with pytest.raises(BackendError,match='Qwen web session token'): QwenAdapter('  ')

def test_list_models_and_check_token(monkeypatch):
    def handler(m,u,kw):
        if u.endswith('/api/v1/auths/'): return Resp(obj={'id':'user','email':'a@b'})
        return Resp(obj={'data':[{'id':'qwen3.7-plus','info':{'meta':{'chat_type':['t2t','t2i']}}},{'id':'img-only','info':{'meta':{'chat_type':['t2i']}}},{'id':'qwen3.8-max','info':{'meta':{'chat_type':['t2t']}}}]})
    calls=install(monkeypatch,handler)
    api=QwenAdapter(TOKEN)
    assert api.check_token() is True
    assert api.list_models()==['qwen3.7-plus','qwen3.8-max']
    assert [c['method'] for c in calls]==['GET','GET']

def test_continue_sends_follow_up_in_same_chat(monkeypatch):
    lines=[sse({'response.created':{'chat_id':'chat-1','response_id':'resp-2'}}),
           sse({'choices':[{'delta':{'phase':'answer','content':'rest','status':'finished'},'finish_reason':'stop'}]})]
    calls=install(monkeypatch,lambda m,u,kw: Resp(lines=lines))
    parts=list(QwenAdapter(TOKEN).continue_answer('chat-1','resp-1'))
    assert [(p['type'],p['content']) for p in parts]==[('text','rest'),('complete','')] and parts[-1]['message_id']=='resp-2'
    payload=calls[0]['json']; assert payload['parent_id']=='resp-1' and payload['messages'][0]['parent_id']=='resp-1'
    assert payload['messages'][0]['content'].endswith(CONTINUE_PROMPT) and QwenAdapter.supports_continue is True

def test_inline_code_can_be_disabled(monkeypatch):
    calls=install(monkeypatch,lambda m,u,kw: Resp(lines=[sse({'choices':[{'delta':{'phase':'answer','content':'x','status':'finished'},'finish_reason':'stop'}]})]))
    api=QwenAdapter(TOKEN); api.inline_code=False; list(api.stream('chat-1','Hi'))
    msg=calls[0]['json']['messages'][0]; assert msg['content']=='Hi' and 'code_interpreter' not in msg['feature_config']

def test_storage_adds_provider_column_with_backup(tmp_path):
    path=tmp_path/'old.db'; s=Storage(path); cid=s.create(); s.db.execute('ALTER TABLE conversations DROP COLUMN provider'); s.db.commit(); s.db.close()
    s=Storage(path)
    assert s.conversations()[0]['provider']=='deepseek'
    assert path.with_suffix('.pre-provider.bak').exists()
    assert s.settings()['provider']=='deepseek' and s.settings()['qwen_model']==QWEN_DEFAULT_MODEL
    s.db.close()

def run_worker(worker):
    loop=QEventLoop(); worker.done.connect(loop.quit); worker.start(); QTimer.singleShot(5000,loop.quit); loop.exec(); worker.wait(2000)

def test_worker_uses_qwen_adapter_and_saves_string_parent(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'w.db'); cid=store.create(provider='qwen'); uid=store.add(cid,'user','hello','pending'); store.db.close()
    seen={}
    class FakeQwen:
        def __init__(self,token,timeout,cancel,model): seen.update(token=token,model=model)
        def create_session(self): return 'chat-1'
        def stream(self,session,prompt,parent,thinking,search,auto_continue):
            seen['parent']=parent
            yield {'type':'text','content':'hi','message_id':'resp-1'}
            yield {'type':'complete','content':'','message_id':'resp-1'}
    class NoDeepSeek:
        def __init__(self,*a): raise AssertionError('DeepSeek adapter must not be used')
    monkeypatch.setattr('app.ui.main_window.QwenAdapter',FakeQwen); monkeypatch.setattr('app.ui.main_window.Adapter',NoDeepSeek)
    options=dict(timeout=30,thinking=False,search=False,streaming=True,auto_continue=True,qwen_model='qwen3.8-max',qwen_transport='http')
    run_worker(mw.Worker(TOKEN,None,None,'hello',options,tmp_path/'w.db',cid,user_id=uid,provider='qwen'))
    store=Storage(tmp_path/'w.db'); row=store.conversations()[0]; msgs=store.messages(cid)
    assert seen=={'token':TOKEN,'model':'qwen3.8-max','parent':None}
    assert (row['remote_id'],row['parent_id'],row['pending_id'])==('chat-1','resp-1',None)
    assert [m['status'] for m in msgs]==['sent','sent'] and msgs[1]['content']=='hi'
    store.db.close()

def test_worker_qwen_error_offers_continue(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'e.db'); cid=store.create(provider='qwen'); uid=store.add(cid,'user','hello','pending'); store.db.close()
    class FakeQwen:
        def __init__(self,*a): pass
        def create_session(self): return 'chat-1'
        def stream(self,*a):
            yield {'type':'text','content':'part','message_id':'resp-1'}
            raise BackendError('Qwen rate limit reached. Wait before retrying.')
    monkeypatch.setattr('app.ui.main_window.QwenAdapter',FakeQwen)
    errors=[]; options=dict(timeout=30,thinking=False,search=False,streaming=True,auto_continue=True,qwen_transport='http')
    w=mw.Worker(TOKEN,None,None,'hello',options,tmp_path/'e.db',cid,user_id=uid,provider='qwen'); w.failed.connect(errors.append); run_worker(w)
    store=Storage(tmp_path/'e.db'); row=store.conversations()[0]
    assert row['pending_id']=='resp-1' and row['parent_id']=='resp-1'
    assert errors and 'Qwen' in errors[0]
    store.db.close()

class FakeVault:
    data={}
    def get_password(self,service,user): return self.data.get((service,user))
    def set_password(self,service,user,value): self.data[(service,user)]=value
    def delete_password(self,service,user): self.data.pop((service,user))

def test_settings_saves_separate_qwen_token_and_provider(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    FakeVault.data={('DeepSeekDesktop','web-session'):'deepseek-token'}
    monkeypatch.setattr('app.ui.main_window.WinVaultKeyring',FakeVault)
    store=Storage(tmp_path/'s.db'); window=mw.Window(store)
    dialog=mw.Settings(window,store.settings())
    dialog.provider.setCurrentIndex(1); dialog.qwen_token.setText('  "Bearer qwen-jwt"  '); dialog.qwen_model.setCurrentText('qwen3.8-max'); dialog.save()
    assert FakeVault.data==({('DeepSeekDesktop','web-session'):'deepseek-token',('DeepSeekDesktop','qwen-web-session'):'qwen-jwt'})
    assert dialog.values['provider']=='qwen' and dialog.values['qwen_model']=='qwen3.8-max'
    assert mw.credential('qwen')=='qwen-jwt' and mw.credential()=='deepseek-token'
    dialog=mw.Settings(window,dict(dialog.values)); dialog.qwen_remove.setChecked(True); dialog.save()
    assert FakeVault.data=={('DeepSeekDesktop','web-session'):'deepseek-token'}
    window.close(); store.db.close()

def test_chat_provider_binding(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'b.db'); window=mw.Window(store)
    old=store.create(provider='deepseek'); store.execute('UPDATE conversations SET remote_id=? WHERE id=?',('77',old))
    fresh=store.create(provider='deepseek')
    window.options['provider']='qwen'
    window.cid=old; assert window.chat_provider()=='deepseek' and window.bind_provider()['provider']=='deepseek'
    window.cid=fresh; assert window.chat_provider()=='qwen' and window.bind_provider()['provider']=='qwen'
    window.render(); assert 'Qwen' in window.provider_label.text()
    window.close(); store.db.close()

def test_persian_errors_for_qwen():
    assert 'VPN' in mw.persian_error('Qwen is not available in your region (HTTP 405).','qwen')
    assert 'کپچا' in mw.persian_error('Qwen web firewall (Alibaba WAF) returned a captcha page','qwen')
    assert 'Qwen' in mw.persian_error('Qwen rate limit reached. Wait before retrying.','qwen')
    assert 'DeepSeek' in mw.persian_error('DeepSeek rate limit reached.')
