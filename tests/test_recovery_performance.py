import os, subprocess, sys, time, sqlite3
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.ui.main_window import Window, Worker
from app.backend.deepseek_adapter import BackendError


def test_500_messages_are_paged_and_render_quickly(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'history.db'); cid=store.create()
    for i in range(500): store.add(cid,'assistant',f'message {i}\n```python\nprint({i})\n```')
    start=time.monotonic(); window=Window(store); window.cid=cid; window.render()
    assert time.monotonic()-start < 5
    assert len(store.messages_page(cid))==50
    assert 'message 499' in window.chat.toPlainText()
    assert 'message 0' not in window.chat.toPlainText()
    window.load_older()
    assert 'message 449' in window.chat.toPlainText()
    window.close()


def test_legacy_database_is_backed_up_before_migration(tmp_path):
    path=tmp_path/'legacy.db'
    db=sqlite3.connect(path)
    db.executescript("CREATE TABLE conversations(id INTEGER PRIMARY KEY,title TEXT NOT NULL,remote_id TEXT,parent_id TEXT,thinking INTEGER DEFAULT 0,search INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE messages(id INTEGER PRIMARY KEY,conversation_id INTEGER,role TEXT,content TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);")
    db.execute("INSERT INTO conversations(id,title) VALUES (1,'old')")
    db.execute("INSERT INTO messages(conversation_id,role,content) VALUES (1,'user','preserved')")
    db.commit(); db.close()
    store=Storage(path)
    assert path.with_suffix('.pre-status.bak').exists()
    assert store.messages(1)[0]['content']=='preserved'
    assert store.messages(1)[0]['status']=='sent'
    store.db.close()


def test_long_code_message_renders_and_copies(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'long.db'); cid=store.create(); code='print(1)\n'*10000
    store.add(cid,'assistant','```python\n'+code+'```')
    start=time.monotonic(); window=Window(store); window.cid=cid; window.render()
    assert time.monotonic()-start<5
    assert window.code_blocks[0].startswith('print(1)')
    window.close()


def test_abrupt_exit_preserves_pending_user_message(tmp_path):
    path=tmp_path/'crash.db'
    script='from app.database.storage import Storage; import os,sys; s=Storage(sys.argv[1]); c=s.create(); s.add(c,"user","committed", "pending"); os._exit(1)'
    subprocess.run([sys.executable,'-c',script,str(path)],check=False,cwd=os.getcwd())
    store=Storage(path); store.recover_interrupted()
    row=store.messages(store.conversations()[0]['id'])[0]
    assert row['content']=='committed' and row['status']=='interrupted'
    store.db.close()


def test_abrupt_exit_preserves_partial_assistant_and_continue_id(tmp_path):
    path=tmp_path/'partial.db'
    script='from app.database.storage import Storage; import os,sys; s=Storage(sys.argv[1]); c=s.create(); u=s.add(c,"user","hello","pending"); s.acknowledge_response(c,u,123); s.add(c,"assistant","partial code: ```py\\nprint(1)","streaming"); os._exit(1)'
    subprocess.run([sys.executable,'-c',script,str(path)],check=False,cwd=os.getcwd())
    store=Storage(path); store.recover_interrupted()
    row=store.conversations()[0]; messages=store.messages(row['id'])
    assert messages[0]['status']=='sent'
    assert messages[1]['status']=='interrupted' and messages[1]['content'].startswith('partial code')
    assert row['pending_id']=='123'
    store.db.close()


def test_worker_persists_partial_response_and_keeps_gui_responsive(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'worker.db'); cid=store.create(); uid=store.add(cid,'user','hello','pending'); store.db.close()
    class FakeAdapter:
        def __init__(self,*args): pass
        def create_session(self): return 'remote-session'
        def stream(self,*args):
            for i in range(40):
                time.sleep(.01)
                yield {'type':'text','content':'x','message_id':123}
            raise BackendError('The connection was interrupted during streaming.')
    monkeypatch.setattr('app.ui.main_window.Adapter',FakeAdapter)
    options=dict(timeout=30,thinking=False,search=False,streaming=True,auto_continue=True)
    worker=Worker('secret',None,None,'hello',options,tmp_path/'worker.db',cid,user_id=uid)
    loop=QEventLoop(); ticks=[]; timer=QTimer(); timer.timeout.connect(lambda:ticks.append(1)); timer.start(20)
    worker.done.connect(loop.quit); worker.start(); QTimer.singleShot(5000,loop.quit); loop.exec(); worker.wait(2000); timer.stop()
    assert not worker.isRunning() and len(ticks)>5
    store=Storage(tmp_path/'worker.db'); rows=store.messages(cid)
    assert rows[0]['status']=='sent'
    assert rows[1]['content']=='x'*40 and rows[1]['status']=='interrupted'
    assert store.conversations()[0]['pending_id']=='123'
    store.db.close()


def test_failed_request_does_not_mark_user_message_sent(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store=Storage(tmp_path/'failed.db'); cid=store.create(); uid=store.add(cid,'user','hello','pending'); store.db.close()
    class FakeAdapter:
        def __init__(self,*args): pass
        def create_session(self): raise BackendError('Network connection failed')
    monkeypatch.setattr('app.ui.main_window.Adapter',FakeAdapter)
    options=dict(timeout=30,thinking=False,search=False,streaming=True,auto_continue=True)
    worker=Worker('secret',None,None,'hello',options,tmp_path/'failed.db',cid,user_id=uid)
    loop=QEventLoop(); worker.done.connect(loop.quit); worker.start(); QTimer.singleShot(5000,loop.quit); loop.exec(); worker.wait(2000)
    store=Storage(tmp_path/'failed.db')
    assert store.messages(cid)[0]['status']=='failed'
    assert len(store.messages(cid))==1
    store.db.close()
