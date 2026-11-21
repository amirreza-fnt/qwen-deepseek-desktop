"""Direct HTTP transport for the unofficial chat.qwen.ai web API (fallback).

Uses only the user's web session token (``Authorization: Bearer``). Since 2026
Alibaba's WAF usually answers such non-browser requests with a captcha page;
the default transport is therefore the built-in browser
(``qwen_browser_transport.QwenBrowserAdapter``). Protocol details, payloads and
the SSE parser live in ``qwen_protocol`` and are shared by both transports.
No cookies are imported, no captcha or WAF signature is generated or solved,
and nothing is retried automatically.
"""
import json, threading, uuid
from curl_cffi import requests
from .deepseek_adapter import BackendError, Cancelled, logger
from .qwen_protocol import (QWEN_BASE, QWEN_SPA_VERSION, QWEN_DEFAULT_MODEL, QWEN_FALLBACK_MODELS, QwenVerificationRequired,
                            QwenStreamState, qwen_shape, error_code, raise_for_code, raise_for_status, parse_json_reply,
                            new_chat_payload, chat_id_from, models_from, check_parent, chat_payload, finish_stream,
                            token_expired, MANUAL_TOKEN_EXPIRED, CONTINUE_PROMPT)

# Backwards-compatible aliases.
_error_code = error_code

def _read_body(r, limit=20000, stream=False):
    """Read at most ``limit`` bytes from a response (streaming responses are read chunk by chunk)."""
    try:
        if stream and hasattr(r, 'iter_content'):
            buf = b''
            for part in r.iter_content():
                if part: buf += part if isinstance(part, bytes) else str(part).encode('utf-8')
                if len(buf) >= limit: break
            return buf[:limit]
        content = getattr(r, 'content', b'')
        return (content if isinstance(content, bytes) else str(content).encode('utf-8'))[:limit]
    except Exception:
        return b''

class QwenAdapter:
    BASE = QWEN_BASE
    SPA_VERSION = QWEN_SPA_VERSION
    provider = 'qwen'
    supports_continue = True
    inline_code = True

    def __init__(self, token, timeout=60, cancel=None, model=None):
        self.token = (token or '').strip()
        if self.token.lower().startswith('bearer '): self.token = self.token[7:].strip()
        if not self.token: raise BackendError('Enter a Qwen web session token in Settings.')
        self.timeout = timeout
        self.cancel = cancel or threading.Event()
        self.model = (model or QWEN_DEFAULT_MODEL).strip() or QWEN_DEFAULT_MODEL

    def headers(self, chat_id=None, stream=False):
        return {'authorization': 'Bearer ' + self.token, 'content-type': 'application/json',
                'accept': 'text/event-stream' if stream else 'application/json, text/plain, */*',
                'origin': self.BASE, 'referer': f'{self.BASE}/c/{chat_id}' if chat_id else self.BASE + '/',
                'source': 'web', 'version': self.SPA_VERSION, 'x-request-id': str(uuid.uuid4()),
                'x-accel-buffering': 'no', 'accept-language': 'en-US,en;q=0.9'}

    def request(self, method, path, data=None, chat_id=None, stream=False):
        if self.cancel.is_set(): raise Cancelled()
        short = path.split('?', 1)[0]
        logger.info('qwen request_start transport=http path=%s streaming=%s', short, stream)
        if token_expired(self.token):
            logger.info('qwen manual_token_expired transport=http')
            raise QwenVerificationRequired(MANUAL_TOKEN_EXPIRED)
        try:
            r = requests.request(method, self.BASE + path, headers=self.headers(chat_id, stream), json=data,
                                 impersonate='chrome120', timeout=self.timeout, stream=stream)
        except requests.exceptions.RequestException as e:
            raise BackendError('Network connection failed or timed out. Please retry.') from e
        status = r.status_code
        content_type = getattr(r, 'headers', {}).get('content-type', 'unknown').split(';', 1)[0].lower()
        logger.info('qwen request=%s status=%s content_type=%s', short, status, content_type)
        cache = []
        def body():
            if not cache: cache.append(_read_body(r, 20000, stream))
            return cache[0]
        try:
            raise_for_status(status, content_type, body, logger, short)
        except BackendError:
            r.close(); raise
        return r

    def json_request(self, method, path, data=None):
        r = self.request(method, path, data)
        try: body = _read_body(r, 5_000_000)
        finally: r.close()
        return parse_json_reply(body, logger, path.split('?', 1)[0])

    def check_token(self):
        """GET /api/v1/auths/ - read-only check that the token is accepted."""
        obj = self.json_request('GET', '/api/v1/auths/')
        return bool(obj.get('id') or obj.get('email') or obj.get('token') or obj.get('name'))

    def list_models(self):
        return models_from(self.json_request('GET', '/api/models'))

    def create_session(self):
        return chat_id_from(self.json_request('POST', '/api/v2/chats/new', new_chat_payload(self.model)))

    def build_payload(self, session, prompt, parent=None, thinking=False, search=False):
        return chat_payload(self.model, session, prompt, parent, thinking, search, self.inline_code)

    def stream(self, session, prompt, parent=None, thinking=False, search=False, auto_continue=True):
        if not session: raise BackendError('Missing Qwen session ID. Start a new chat.')
        parent = check_parent(parent)
        payload = self.build_payload(session, prompt, parent, thinking, search)
        response = self.request('POST', f'/api/v2/chat/completions?chat_id={session}', payload, chat_id=session, stream=True)
        state = QwenStreamState(logger)
        try:
            content_type = getattr(response, 'headers', {}).get('content-type', '').lower()
            if 'application/json' in content_type:
                obj = parse_json_reply(_read_body(response, 65536, True), logger, '/api/v2/chat/completions')
                raise BackendError('Qwen did not return a stream; the private API may have changed.')
            for line in response.iter_lines():
                if self.cancel.is_set(): raise Cancelled()
                for chunk in state.feed(line): yield chunk
                if state.done: break
        except requests.exceptions.RequestException as e:
            raise BackendError('The connection was interrupted during streaming.') from e
        finally: response.close()
        for chunk in state.flush(): yield chunk
        yield finish_stream(state, logger)

    def continue_answer(self, session, message_id, auto_continue=True, existing_text=''):
        logger.info('qwen continue_requested')
        yield from self.stream(session, CONTINUE_PROMPT, message_id, False, False)
