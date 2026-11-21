"""Regression tests for the Qwen "log in again" loop (20 Nov 2026).

Root cause: an expired manual token saved in Settings (Qwen web tokens live ~15 minutes) overrode the
fresh token of the logged-in built-in browser page; chats/new then answered HTTP 200 with
{"success":false,"data":{"code":"unauthorized","details":"Token has expired, please log in again."}}
and the over-broad error mapper (any code containing "login"/"limit") hid the real server message.
"""
import base64, json, logging, os, queue, time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from app.backend.deepseek_adapter import BackendError
from app.backend import qwen_protocol as qp
from app.backend.qwen_protocol import QwenVerificationRequired, classify_code, error_code, raise_for_code, redact, token_expired, parse_json_reply, raise_for_status
from app.backend.qwen_browser_transport import QwenBrowserAdapter
from app.backend.qwen_adapter import QwenAdapter
import app.ui.main_window as mw

LIVE_EXPIRED = {"success": False, "request_id": "cddd433c-da09-455e-a667-67f5a271d6be",
                "data": {"code": "unauthorized", "details": "Token has expired, please log in again."}}

def jwt(exp):
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
    return enc({'alg': 'HS256', 'typ': 'JWT'}) + '.' + enc({'id': 'user-1', 'exp': exp, 'iat': exp - 900}) + '.c2lnbmF0dXJlLXNpZ25hdHVyZQ'

class Bridge:
    def __init__(self, events): self.events = events; self.specs = []; self.aborted = []
    def submit(self, spec):
        self.specs.append(spec); q = queue.Queue()
        for e in self.events: q.put(e)
        return 'r%d' % len(self.specs), q
    def abort(self, rid): self.aborted.append(rid)

def reply(obj, status=200):
    return [{'kind': 'meta', 'status': status, 'ctype': 'application/json'}, {'kind': 'data', 'text': json.dumps(obj)}, {'kind': 'end'}]

def test_live_unauthorized_envelope_maps_to_login_with_server_details(caplog):
    caplog.set_level(logging.INFO, logger='deepseek_desktop.backend')
    api = QwenBrowserAdapter(Bridge(reply(LIVE_EXPIRED)))
    with pytest.raises(QwenVerificationRequired) as e: api.create_session()
    assert 'unauthorized: Token has expired, please log in again.' in str(e.value)
    assert 'mapper=auth' in caplog.text and 'error_code=unauthorized' in caplog.text

@pytest.mark.parametrize('code,branch', [
    ('unauthorized:Token has expired, please log in again.', 'auth'), ('Unauthorized:', 'auth'), ('401:', 'auth'),
    ('ERROR:Your session has expired, please login again', 'auth'), ('NotLogin:', 'auth'),
    ('RateLimited:x', 'rate'), ('ParallelLimited:', 'rate'), ('Bad_Request:too many requests', 'rate'),
    ('WAF', 'waf'), ('FAIL_SYS_USER_VALIDATE', 'waf'),
    ('Not_Found:chat not exist', 'not_found'), ('ModelNotFound:', 'model'),
    # These used to be reported as "log in again" / "rate limit" because of bare 'login'/'limit' substrings:
    ('Bad_Request:field login_type is invalid', 'other'), ('LoginMethodDisabled:', 'other'),
    ('Content_Security_Check_Failed:input too long', 'other'), ('FileSizeLimitExceeded:', 'other'),
])
def test_mapper_branches_are_narrow(code, branch):
    assert classify_code(code) == branch

def test_unknown_codes_report_the_real_server_code():
    with pytest.raises(BackendError) as e: raise_for_code('Content_Security_Check_Failed:input contains sensitive content')
    assert not isinstance(e.value, QwenVerificationRequired)
    assert '[Qwen server: Content_Security_Check_Failed: input contains sensitive content]' in str(e.value)

def test_error_bodies_are_logged_redacted(caplog):
    caplog.set_level(logging.INFO, logger='deepseek_desktop.backend')
    secret = jwt(int(time.time()) + 600)
    body = json.dumps({'success': False, 'data': {'code': 'Bad_Request', 'details': 'bad token ' + secret + ' for a@b.com'}}).encode()
    with pytest.raises(BackendError): parse_json_reply(body, qp_logger(), '/api/v2/chats/new')
    with pytest.raises(BackendError): raise_for_status(500, 'application/json', lambda: body, qp_logger(), '/api/v2/chats/new')
    assert secret not in caplog.text and 'a@b.com' not in caplog.text
    assert 'error_body=' in caplog.text and 'mapper=other' in caplog.text and '<jwt>' in caplog.text

def qp_logger():
    from app.backend.deepseek_adapter import logger
    return logger

def test_redact_helpers():
    t = jwt(2000000000)
    out = redact('Authorization: Bearer abc.def {"token":"' + t + '"} me@example.com ' + 'x' * 50)
    assert t not in out and 'abc.def' not in out and 'me@example.com' not in out and 'x' * 50 not in out
    assert len(redact('a' * 1000 + ' b' * 400)) <= 300

def test_token_expiry_helpers():
    now = time.time()
    assert token_expired(jwt(int(now) - 1)) and not token_expired(jwt(int(now) + 600))
    assert not token_expired('not-a-jwt') and not token_expired('')

def test_expired_manual_token_is_not_sent_by_browser_transport(caplog):
    caplog.set_level(logging.INFO, logger='deepseek_desktop.backend')
    expired = jwt(int(time.time()) - 3600)
    bridge = Bridge(reply({'success': True, 'data': {'id': 'chat-9'}}))
    assert QwenBrowserAdapter(bridge, token=expired).create_session() == 'chat-9'
    assert bridge.specs[0]['token'] == ''  # page token is used instead
    assert 'manual_token_ignored reason=expired' in caplog.text and expired not in caplog.text
    fresh = jwt(int(time.time()) + 600); bridge = Bridge(reply({'success': True, 'data': {'id': 'c'}}))
    QwenBrowserAdapter(bridge, token=fresh).create_session(); assert bridge.specs[0]['token'] == fresh  # fallback only

def test_page_token_has_priority_in_start_js():
    from app.ui.qwen_browser import START_JS
    page = START_JS.index("localStorage.getItem('token')"); manual = START_JS.index('spec.token')
    assert page < manual and "if (!token && spec.token)" in START_JS and 'stale-token' in START_JS

def test_http_transport_rejects_expired_manual_token_without_network(monkeypatch):
    import app.backend.qwen_adapter as qa
    monkeypatch.setattr(qa.requests, 'request', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network used')))
    with pytest.raises(QwenVerificationRequired, match='15 minutes'): QwenAdapter(jwt(int(time.time()) - 5)).create_session()

def test_persian_dialog_shows_real_server_error():
    msg = qp.TOKEN_MESSAGE + qp.server_suffix('unauthorized', 'Token has expired, please log in again.')
    fa = mw.persian_error(msg, 'qwen')
    assert 'دوباره وارد' in fa and 'unauthorized: Token has expired, please log in again.' in fa and 'پاسخ سرور' in fa
    other = mw.persian_error('Qwen rejected the request. [Qwen server: Content_Security_Check_Failed: blocked]', 'qwen')
    assert 'Content_Security_Check_Failed: blocked' in other and 'وارد' not in other
    assert '۱۵ دقیقه' in mw.persian_error(qp.MANUAL_TOKEN_EXPIRED, 'qwen')

def test_settings_status_flags_expired_saved_qwen_token(monkeypatch):
    store = {('DeepSeekDesktop', 'qwen-web-session'): jwt(int(time.time()) - 60)}
    class Vault:
        def get_password(self, s, u): return store.get((s, u))
    monkeypatch.setattr(mw, 'WinVaultKeyring', Vault)
    assert 'منقضی' in mw.Settings.token_status('qwen')
