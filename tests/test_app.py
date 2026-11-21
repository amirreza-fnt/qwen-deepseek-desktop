import os, threading
os.environ['QT_QPA_PLATFORM']='offscreen'
import pytest
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.backend.deepseek_adapter import Adapter, BackendError, Cancelled
from app.ui.main_window import Window

def test_storage_restart(tmp_path):
    path=tmp_path/'history.db'; s=Storage(path); cid=s.create('Hello'); s.add(cid,'user','message'); s.db.close(); s=Storage(path)
    assert s.conversations()[0]['title']=='Hello'; assert s.messages(cid)[0]['content']=='message'; s.db.close()

def test_pending_continuation_survives_restart(tmp_path):
    path=tmp_path/'history.db'; s=Storage(path); cid=s.create()
    s.execute('UPDATE conversations SET remote_id=?,parent_id=?,pending_id=? WHERE id=?',('session','42','42',cid))
    assert s.settings()['auto_continue'] is True
    s.db.close(); s=Storage(path)
    row=s.conversations()[0]
    assert (row['remote_id'],row['parent_id'],row['pending_id'])==('session','42','42')
    s.db.close()

def test_startup_and_markdown(tmp_path):
    app=QApplication.instance() or QApplication([]); s=Storage(tmp_path/'db'); cid=s.create(); s.add(cid,'assistant','**bold**'); w=Window(s); w.cid=cid; w.render(); assert 'bold' in w.chat.toPlainText(); w.close()

def test_cancel_before_request():
    e=threading.Event(); e.set(); a=Adapter('token',cancel=e)
    with pytest.raises(Cancelled): a.create_session()

def test_rate_limit(monkeypatch):
    class Response:
        status_code=429
        def close(self): pass
    monkeypatch.setattr('app.backend.deepseek_adapter.requests.post',lambda *a,**k:Response())
    with pytest.raises(BackendError,match='rate limit'): Adapter('token').create_session()

def test_session_and_stream(monkeypatch):
    class Response:
        status_code=200; headers={'content-type':'application/json'}
        def __init__(self,obj=None): self.obj=obj; self.headers={'content-type':'application/json' if obj else 'text/event-stream'}
        def json(self): return self.obj
        def close(self): pass
        def iter_lines(self): yield b'data: {"choices":[{"delta":{"content":"hello","type":"text"},"finish_reason":"stop"}]}'
    def post(url,**kw):
        if url.endswith('/chat_session/create'): return Response({'code':0,'data':{'biz_code':0,'biz_data':{'chat_session':{'id':'s'}}}})
        if url.endswith('/chat/create_pow_challenge'): return Response({'code':0,'data':{'biz_data':{'challenge':{}}}})
        return Response()
    monkeypatch.setattr('app.backend.deepseek_adapter.requests.post',post)
    a=Adapter('token'); a.pow.solve_challenge=lambda x:'proof'
    assert a.create_session()=='s'; assert list(a.stream('s','Hi'))[0]['content']=='hello'

@pytest.mark.parametrize('payload,expected', [
    ({'code':40003,'msg':'INVALID_TOKEN','data':None}, 'invalid or expired'),
    ({'code':0,'data':{'biz_data':{}}}, 'no session ID'),
    ({'data':{'biz_data':{'id':'s'}}}, 'rejected'),
])
def test_unexpected_session_responses(monkeypatch,payload,expected):
    class Response:
        status_code=200; headers={'content-type':'application/json'}
        def json(self): return payload
        def close(self): pass
    monkeypatch.setattr('app.backend.deepseek_adapter.requests.post',lambda *a,**k:Response())
    with pytest.raises(BackendError,match=expected): Adapter('secret').create_session()

def test_legacy_session_response(monkeypatch):
    class Response:
        status_code=200; headers={'content-type':'application/json'}
        def json(self): return {'code':0,'data':{'biz_data':{'id':123}}}
        def close(self): pass
    monkeypatch.setattr('app.backend.deepseek_adapter.requests.post',lambda *a,**k:Response())
    assert Adapter('secret').create_session() == '123'

def test_current_stream_fragments(monkeypatch):
    class Response:
        status_code=200; headers={'content-type':'text/event-stream'}
        def close(self): pass
        def iter_lines(self):
            yield b'data: {"response_message_id":42}'
            yield b'data: {"v":{"response":{"fragments":[{"type":"THINK"}]}}}'
            yield b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":"hmm"}'
            yield b'data: {"v":"..."}'
            yield b'data: {"p":"response/fragments","v":[{"type":"THINK"},{"type":"RESPONSE"}]}'
            yield b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":"OK"}'
            yield b'data: {"p":"response/status","o":"SET","v":"FINISHED"}'
    a=Adapter('secret'); a.pow.solve_challenge=lambda _: 'proof'
    a.json_request=lambda *args: {'data':{'biz_data':{'challenge':{}}}}
    monkeypatch.setattr(a,'request',lambda *args: Response())
    parts=list(a.stream('session','prompt',thinking=True))
    assert [(p['type'],p['content']) for p in parts if p['content']] == [('thinking','hmm'),('thinking','...'),('text','OK')]
    assert all(p['message_id']==42 for p in parts)

def test_three_turns_keep_numeric_remote_parent_across_restart(monkeypatch,tmp_path):
    seen=[]
    class Response:
        status_code=200; headers={'content-type':'application/json'}
        def __init__(self,obj=None,mid=None): self.obj=obj; self.mid=mid; self.headers={'content-type':'application/json' if obj else 'text/event-stream'}
        def json(self): return self.obj
        def close(self): pass
        def iter_lines(self):
            yield ('data: {"response_message_id":%d}' % self.mid).encode()
            yield b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":"OK"}'
            yield b'data: {"p":"response/status","o":"SET","v":"FINISHED"}'
    def post(url,**kwargs):
        if url.endswith('/chat_session/create'):
            return Response({'code':0,'data':{'biz_data':{'chat_session':{'id':77}}}})
        if url.endswith('/chat/create_pow_challenge'):
            return Response({'code':0,'data':{'biz_data':{'challenge':{}}}})
        seen.append(kwargs['json'])
        return Response(mid=100+len(seen))
    monkeypatch.setattr('app.backend.deepseek_adapter.requests.post',post)
    db=Storage(tmp_path/'history.db'); cid=db.create()
    api=Adapter('secret'); api.pow.solve_challenge=lambda _: 'proof'
    remote=api.create_session(); db.execute('UPDATE conversations SET remote_id=? WHERE id=?',(remote,cid))
    for turn in range(3):
        if turn == 1:
            db.db.close(); db=Storage(tmp_path/'history.db')
        row=db.conversations()[0]
        parts=list(api.stream(row['remote_id'],f'prompt {turn}',row['parent_id']))
        db.add(cid,'user',f'prompt {turn}'); db.add(cid,'assistant',''.join(p['content'] for p in parts))
        db.execute('UPDATE conversations SET parent_id=? WHERE id=?',(str(parts[-1]['message_id']),cid))
    assert [p['parent_message_id'] for p in seen] == [None,101,102]
    assert all(p['chat_session_id']=='77' for p in seen)
    assert len(db.messages(cid)) == 6
    db.db.close()

def test_incomplete_response_continues_without_duplicate_text(monkeypatch):
    class Response:
        def __init__(self, lines): self.lines=lines
        def iter_lines(self): return iter(self.lines)
        def close(self): pass
    requests_seen=[]
    first=[b'data: {"response_message_id":42}',
           b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":"Hello"}',
           b'data: {"p":"response/status","o":"SET","v":"INCOMPLETE"}']
    second=[b'data: {"v":{"response":{"message_id":42,"fragments":[{"type":"RESPONSE","content":"Hello"}]}}}',
            b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":" world"}',
            b'data: {"p":"response/status","o":"SET","v":"FINISHED"}']
    a=Adapter('secret'); a.pow.solve_challenge=lambda _: 'proof'
    a.json_request=lambda *args: {'data':{'biz_data':{'challenge':{}}}}
    def request(path,payload,proof=None,stream=False):
        requests_seen.append((path,payload)); return Response(first if len(requests_seen)==1 else second)
    monkeypatch.setattr(a,'request',request)
    monkeypatch.setattr(a.cancel,'wait',lambda seconds: False)
    parts=list(a.stream('session','prompt'))
    assert ''.join(p['content'] for p in parts)=='Hello world'
    assert [p['type'] for p in parts if p['type'] in ('incomplete','complete')]==['incomplete','complete']
    assert requests_seen[1]==('/chat/continue',{'chat_session_id':'session','message_id':42,'fallback_to_resume':True})

def test_auto_continue_stops_after_three_attempts(monkeypatch):
    class Response:
        def iter_lines(self):
            yield b'data: {"response_message_id":42}'
            yield b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":"x"}'
            yield b'data: {"p":"response/status","o":"SET","v":"INCOMPLETE"}'
        def close(self): pass
    a=Adapter('secret'); a.pow.solve_challenge=lambda _: 'proof'
    a.json_request=lambda *args: {'data':{'biz_data':{'challenge':{}}}}
    calls=[]
    monkeypatch.setattr(a,'request',lambda path,*args: (calls.append(path) or Response()))
    monkeypatch.setattr(a.cancel,'wait',lambda seconds: False)
    parts=list(a.stream('session','prompt'))
    assert calls == ['/chat/completion']+['/chat/continue']*3
    assert parts[-1]['type']=='incomplete'

def test_manual_continue_skips_replayed_prefix(monkeypatch):
    class Response:
        def iter_lines(self):
            yield b'data: {"response_message_id":42}'
            yield b'data: {"v":{"response":{"fragments":[{"type":"RESPONSE","content":"Hello"}]}}}'
            yield b'data: {"p":"response/fragments/-1/content","o":"APPEND","v":" world"}'
            yield b'data: {"p":"response/status","o":"SET","v":"FINISHED"}'
        def close(self): pass
    a=Adapter('secret'); monkeypatch.setattr(a,'request',lambda *args:Response())
    parts=list(a.continue_answer('session',42,existing_text='Hello'))
    assert ''.join(p['content'] for p in parts)==' world'
    assert parts[-1]['type']=='complete'
