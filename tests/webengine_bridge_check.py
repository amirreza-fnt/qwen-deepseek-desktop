"""Real QtWebEngine check of the in-page Qwen bridge against a local fake server.

Run as a subprocess by tests/test_qwen_browser.py. Prints one JSON line prefixed
with RESULT=. Uses an off-the-record profile; never contacts chat.qwen.ai.
"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt, QCoreApplication, QTimer
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
try:
    import PySide6.QtWebEngineWidgets  # noqa
except ImportError as e:
    print('RESULT=' + json.dumps({'unavailable': str(e)})); sys.exit(0)
from PySide6.QtWidgets import QApplication
from app.ui.qwen_browser import QwenBrowser
from app.backend.qwen_browser_transport import QwenBrowserAdapter
from app.backend.qwen_protocol import QwenVerificationRequired
from app.backend.deepseek_adapter import BackendError, Cancelled

seen = {'auth': [], 'cookie': [], 'parents': [], 'disconnected': False, 'version': []}

def sse(obj): return ('data: ' + json.dumps(obj) + '\n\n').encode()

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def send_body(self, status, body, ctype):
        self.send_response(status); self.send_header('content-type', ctype); self.send_header('content-length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            # Mimics the real site refreshing its short-lived token on page load.
            body = (b'<!doctype html><html><head><title>fake qwen</title><script>'
                    b'var f = localStorage.getItem("fake_refresh"); if (f) { localStorage.setItem("token", f); localStorage.removeItem("fake_refresh"); }'
                    b'</script></head><body>fake</body></html>')
            self.send_response(200); self.send_header('content-type', 'text/html'); self.send_header('set-cookie', 'wafcookie=abc; Path=/')
            self.send_header('content-length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        if self.path == '/api/models':
            self.record(); self.send_body(200, json.dumps({'data': [{'id': 'm1', 'info': {'meta': {'chat_type': ['t2t']}}}]}).encode(), 'application/json'); return
        self.send_body(404, b'{}', 'application/json')
    def record(self):
        seen['auth'].append(self.headers.get('authorization')); seen['cookie'].append(self.headers.get('cookie') or '')
        seen['version'].append(self.headers.get('version'))
    def do_POST(self):
        length = int(self.headers.get('content-length') or 0); body = json.loads(self.rfile.read(length) or b'{}')
        self.record()
        if self.path == '/api/v2/chats/new':
            if body.get('models') == ['hold']:  # like a request held by the site's anti-bot layer
                time.sleep(12); self.send_body(200, json.dumps({'success': True, 'data': {'id': 'late'}}).encode(), 'application/json'); return
            if body.get('models') == ['waf']:
                self.send_body(200, b'<!doctype html><meta name="aliyun_waf_aa" content="x"><div id="aliyunCaptcha-sliding-slider"></div>', 'text/html; charset=utf-8'); return
            if self.headers.get('authorization') == 'Bearer expired':
                # The exact envelope chat.qwen.ai returned for an expired token on 20 Nov 2026.
                self.send_body(200, b'{"success":false,"request_id":"x","data":{"code":"unauthorized","details":"Token has expired, please log in again."}}', 'application/json'); return
            self.send_body(200, json.dumps({'success': True, 'data': {'id': 'chat-1'}}).encode(), 'application/json'); return
        if self.path.startswith('/api/v2/chat/completions'):
            seen['parents'].append(body.get('parent_id'))
            self.send_response(200); self.send_header('content-type', 'text/event-stream'); self.send_header('cache-control', 'no-cache'); self.send_header('connection', 'close'); self.end_headers()
            rid = 'resp-%d' % len(seen['parents'])
            if body.get('messages', [{}])[0].get('content', '').split('\n\n')[-1] == 'slow':
                try:
                    self.wfile.write(sse({'response.created': {'response_id': rid}})); self.wfile.write(sse({'choices': [{'delta': {'phase': 'answer', 'content': 'first'}}]})); self.wfile.flush()
                    for _ in range(60):
                        time.sleep(0.25); self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    seen['disconnected'] = True
                return
            whole = sse({'response.created': {'chat_id': 'chat-1', 'response_id': rid}}) + sse({'choices': [{'delta': {'phase': 'answer', 'content': 'Hel', 'status': 'typing'}}]})
            pieces = [whole[:37], whole[37:], sse({'choices': [{'delta': {'phase': 'answer', 'content': 'lo', 'status': 'typing'}}]})[:20]]
            rest = sse({'choices': [{'delta': {'phase': 'answer', 'content': 'lo', 'status': 'typing'}}]})[20:] + sse({'choices': [{'delta': {'phase': 'answer', 'content': '', 'status': 'finished'}, 'finish_reason': 'stop'}]})
            for piece in pieces + [rest]:
                self.wfile.write(piece); self.wfile.flush(); time.sleep(0.05)
            return
        self.send_body(404, b'{}', 'application/json')

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); threading.Thread(target=server.serve_forever, daemon=True).start()
base = 'http://127.0.0.1:%d' % server.server_address[1]
app = QApplication(sys.argv)
browser = QwenBrowser(base=base, storage_path=None)
result = {}; finished = threading.Event(); gui_jobs = []

def jwt(exp):
    import base64
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256'}) + '.' + enc({'id': 'u', 'exp': exp}) + '.sig'
FRESH = jwt(int(time.time()) + 3600); STALE = jwt(int(time.time()) - 60)

def gui_js(code):
    """Run JavaScript in the page on the GUI thread and wait for it (page access is GUI-thread only)."""
    done = threading.Event(); gui_jobs.append((code, done)); done.wait(10)

def scenario():
    try:
        api = QwenBrowserAdapter(browser, timeout=20, base=base)
        result['models'] = api.list_models()
        chat = api.create_session(); result['chat'] = chat
        first = list(api.stream(chat, 'hi'))
        result['turn1'] = [(p['type'], p['content'], p['message_id']) for p in first]
        second = list(api.stream(chat, 'again', first[-1]['message_id']))
        result['turn2_text'] = ''.join(p['content'] for p in second)
        try:
            QwenBrowserAdapter(browser, timeout=20, model='waf', base=base).create_session(); result['waf'] = 'no error'
        except QwenVerificationRequired as e: result['waf'] = 'verification:' + str(e)[:40]
        QwenBrowserAdapter(browser, timeout=20, token='manual-ignored', base=base).create_session()  # page token wins
        cancel = threading.Event(); api2 = QwenBrowserAdapter(browser, timeout=20, cancel=cancel, base=base); got = []
        try:
            for p in api2.stream(chat, 'slow'):
                got.append(p['content']); cancel.set()
            result['cancel'] = 'no cancel'
        except Cancelled: result['cancel'] = 'cancelled:' + ''.join(got)
        deadline = time.time() + 10
        while not seen['disconnected'] and time.time() < deadline: time.sleep(0.1)
        result['server_saw_abort'] = seen['disconnected']
        gui_js("localStorage.removeItem('token'); 'ok'")
        try:
            QwenBrowserAdapter(browser, timeout=20, base=base).create_session(); result['no_token'] = 'no error'
        except QwenVerificationRequired as e: result['no_token'] = 'verification:' + str(e)[:40]
        try:  # no page token -> manual fallback is used; server answers with the live 'unauthorized' envelope
            QwenBrowserAdapter(browser, timeout=20, token='expired', base=base).create_session(); result['expired'] = 'no error'
        except QwenVerificationRequired as e: result['expired'] = 'verification:' + str(e)
        # stale page token: the bridge reloads the page, the site refreshes the token, then the request is sent
        gui_js("localStorage.setItem('token', %s); localStorage.setItem('fake_refresh', %s); 'ok'" % (json.dumps(STALE), json.dumps(FRESH)))
        result['refreshed_chat'] = QwenBrowserAdapter(browser, timeout=20, base=base).create_session()
        # a verification overlay holds the request: detected within seconds, request aborted, verification error
        gui_js("var d=document.createElement('div'); d.id='baxia-dialog-content'; d.style.width='300px'; d.style.height='200px'; document.body.appendChild(d); 'ok'")
        started = time.time()
        try:
            QwenBrowserAdapter(browser, timeout=30, model='hold', base=base).create_session(); result['overlay'] = 'no error'
        except QwenVerificationRequired as e: result['overlay'] = 'verification:' + str(e)[:60]
        result['overlay_seconds'] = round(time.time() - started, 1)
        gui_js("document.getElementById('baxia-dialog-content').remove(); 'ok'")
    except BaseException as e:
        result['exception'] = type(e).__name__ + ': ' + str(e)[:300]
    finally:
        finished.set()

def loaded(ok):
    if 'load_ok' in result: return  # later loads are the bridge's own token-refresh reloads
    result['load_ok'] = bool(ok)
    browser.page.runJavaScript("localStorage.setItem('token','page-token'); 'set'", 0, lambda _: threading.Thread(target=scenario, daemon=True).start())

browser.page.loadFinished.connect(loaded); browser.ensure_loaded()
def check():
    while gui_jobs:
        code, done = gui_jobs.pop(0); browser.page.runJavaScript(code, 0, lambda _r, d=done: d.set())
    if finished.is_set():
        auths = [a or '' for a in seen['auth']]
        result['seen'] = {'auth': sorted(set('Bearer FRESH' if a == 'Bearer ' + FRESH else 'Bearer STALE' if a == 'Bearer ' + STALE else a for a in auths)),
                          'last_auth_fresh': bool(auths) and auths[-1] == 'Bearer ' + FRESH, 'cookie_sent': all('wafcookie=abc' in c for c in seen['cookie']),
                          'parents': seen['parents'], 'version': sorted(set(v or '' for v in seen['version']))}
        print('RESULT=' + json.dumps(result), flush=True)
        browser.shutdown(); app.quit()
timer = QTimer(); timer.timeout.connect(check); timer.start(50)
QTimer.singleShot(90000, lambda: (print('RESULT=' + json.dumps(dict(result, timeout=True)), flush=True), app.quit()))
app.exec()
server.shutdown()
