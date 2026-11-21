"""Qwen transport that sends requests from inside the built-in browser page.

``QwenBrowserAdapter`` has the same interface as ``QwenAdapter`` (create_session,
stream, continue_answer, check_token, list_models) and is used by the network
Worker thread. It does not touch QtWebEngine itself: it hands a request spec to
a *bridge* object living on the GUI thread (``app.ui.qwen_browser.QwenBrowser``)
which runs ``window.fetch(..., {credentials: 'include'})`` in the chat.qwen.ai
page (so the site's own cookies and anti-bot scripts apply exactly as in a
normal browser) and pushes events back through a thread-safe queue:

    {'kind': 'meta', 'status': int, 'ctype': str}
    {'kind': 'data', 'text': str}          # raw response text, any chunking
    {'kind': 'end'}
    {'kind': 'error', 'error': 'NO_TOKEN' | 'NETWORK' | 'ABORTED' | 'PAGE_RELOADED' |
                               'NOT_ON_SITE' | 'LOAD_FAILED' | 'UNAVAILABLE', 'message': str}

Bridge interface: ``submit(spec) -> (request_id, queue.Queue)``, ``abort(request_id)``
and optionally ``pump()`` (process GUI events when called on the GUI thread).
The Bearer token is read by page JavaScript from the site's own localStorage
(``token``, refreshed by the site itself); a manual token from Settings is only a
fallback when the page has none. Token values are never logged.
"""
import json, queue, threading, time, uuid
from .deepseek_adapter import BackendError, Cancelled, logger
from .qwen_protocol import (QWEN_BASE, QWEN_SPA_VERSION, QWEN_DEFAULT_MODEL, QwenVerificationRequired, QwenStreamState,
                            LineSplitter, raise_for_status, parse_json_reply, new_chat_payload, chat_id_from, models_from,
                            check_parent, chat_payload, finish_stream, token_expired, CONTINUE_PROMPT)

BRIDGE_ERRORS = {
    'NO_TOKEN': 'Not logged in to Qwen in the built-in browser (no session token in the page). Log in at chat.qwen.ai in the browser window, then retry.',
    'NETWORK': 'The built-in browser could not reach Qwen (network/VPN problem or a verification redirect). Check the connection and the browser window, then retry.',
    'PAGE_RELOADED': 'The built-in Qwen page was reloaded during the request. Make sure chat.qwen.ai is loaded in the browser window, then retry.',
    'NOT_ON_SITE': 'The built-in browser is not on chat.qwen.ai. Return to https://chat.qwen.ai in the browser window, then retry.',
    'LOAD_FAILED': 'The built-in browser could not load chat.qwen.ai. Check the connection/VPN and the browser window, then retry.',
    'VERIFICATION': 'Qwen web firewall verification (slider) is waiting in the built-in browser page; the request was held by it and has been cancelled. Complete the slider yourself in the browser window, click Continue, then resend. This app never solves captchas.',
    'TOKEN_STALE': 'The Qwen login in the built-in browser has expired and the page could not refresh it. Log in again in the browser window, then retry.',
}

class QwenBrowserAdapter:
    provider = 'qwen'
    supports_continue = True
    inline_code = True  # switch off code interpreter/tools and ask for fenced code in the reply

    def __init__(self, bridge, timeout=60, cancel=None, model=None, token='', base=QWEN_BASE):
        if bridge is None: raise BackendError('The built-in browser (QtWebEngine) is not available in this build.')
        self.bridge = bridge
        self.timeout = timeout
        self.cancel = cancel or threading.Event()
        self.model = (model or QWEN_DEFAULT_MODEL).strip() or QWEN_DEFAULT_MODEL
        token = (token or '').strip().strip('"\'').strip()
        if token.lower().startswith('bearer '): token = token[7:].strip()
        # Optional manual token. The page's own localStorage token always wins (the site refreshes it every
        # ~15 minutes); the manual token is only a fallback when the page has none, and is ignored once expired.
        if token and token_expired(token):
            logger.info('qwen manual_token_ignored reason=expired')
            token = ''
        self.token = token
        self.base = base.rstrip('/')

    # ----- low level -------------------------------------------------------
    def _spec(self, method, path, data, stream):
        headers = {'content-type': 'application/json', 'accept': 'text/event-stream' if stream else 'application/json, text/plain, */*',
                   'source': 'web', 'version': QWEN_SPA_VERSION, 'x-request-id': str(uuid.uuid4())}
        if stream: headers['x-accel-buffering'] = 'no'
        return {'method': method, 'url': self.base + path, 'headers': headers,
                'body': json.dumps(data) if data is not None else None, 'stream': bool(stream),
                'token': self.token, 'limit': 5_000_000}

    def _get(self, rid, q, wait):
        """Next bridge event; honours cancellation and the inactivity timeout."""
        deadline = time.monotonic() + wait
        pump = getattr(self.bridge, 'pump', None)
        while True:
            if self.cancel.is_set():
                self.bridge.abort(rid); raise Cancelled()
            if pump: pump()
            try: return q.get(timeout=0.03)
            except queue.Empty: pass
            if time.monotonic() >= deadline: return None

    def _raise_bridge_error(self, event):
        code = event.get('error')
        logger.info('qwen browser_error code=%s', code)
        if code == 'ABORTED':
            if self.cancel.is_set(): raise Cancelled()
            raise BackendError('The connection was interrupted during streaming.')
        if code == 'UNAVAILABLE': raise BackendError('The built-in browser (QtWebEngine) is not available in this build.')
        raise QwenVerificationRequired(BRIDGE_ERRORS.get(code, BRIDGE_ERRORS['NETWORK']))

    def _open(self, method, path, data=None, stream=False):
        if self.cancel.is_set(): raise Cancelled()
        short = path.split('?', 1)[0]
        logger.info('qwen request_start transport=browser path=%s streaming=%s', short, stream)
        rid, q = self.bridge.submit(self._spec(method, path, data, stream))
        event = self._get(rid, q, self.timeout)
        if event is None:
            self.bridge.abort(rid)
            raise QwenVerificationRequired(f'No response from Qwen within {self.timeout} seconds. The built-in browser may be waiting for a login or verification; check the browser window, then retry.')
        if event.get('kind') == 'error': self._raise_bridge_error(event)
        if event.get('kind') != 'meta':
            self.bridge.abort(rid); raise BackendError('Unexpected browser bridge event; the private API may have changed.')
        status = int(event.get('status') or 0); ctype = (event.get('ctype') or 'unknown').split(';', 1)[0].lower()
        logger.info('qwen request=%s status=%s content_type=%s', short, status, ctype)
        return rid, q, status, ctype, short

    def _collect(self, rid, q, limit=5_000_000):
        parts = []; size = 0
        while True:
            event = self._get(rid, q, self.timeout)
            if event is None:
                self.bridge.abort(rid); raise BackendError('Network connection failed or timed out. Please retry.')
            kind = event.get('kind')
            if kind == 'data':
                text = event.get('text') or ''
                parts.append(text); size += len(text)
                if size > limit: self.bridge.abort(rid); break
            elif kind == 'end': break
            elif kind == 'error': self._raise_bridge_error(event)
        return ''.join(parts).encode('utf-8')

    def _check(self, rid, q, status, ctype, short):
        cache = []
        def body():
            if not cache: cache.append(self._collect(rid, q, 20000))
            return cache[0]
        raise_for_status(status, ctype, body, logger, short)

    def json_request(self, method, path, data=None):
        rid, q, status, ctype, short = self._open(method, path, data, False)
        self._check(rid, q, status, ctype, short)
        return parse_json_reply(self._collect(rid, q), logger, short)

    # ----- API -------------------------------------------------------------
    def check_token(self):
        obj = self.json_request('GET', '/api/v1/auths/')
        return bool(obj.get('id') or obj.get('email') or obj.get('token') or obj.get('name'))

    def list_models(self):
        return models_from(self.json_request('GET', '/api/models'))

    def create_session(self):
        return chat_id_from(self.json_request('POST', '/api/v2/chats/new', new_chat_payload(self.model)))

    def stream(self, session, prompt, parent=None, thinking=False, search=False, auto_continue=True):
        if not session: raise BackendError('Missing Qwen session ID. Start a new chat.')
        parent = check_parent(parent)
        payload = chat_payload(self.model, session, prompt, parent, thinking, search, self.inline_code)
        rid, q, status, ctype, short = self._open('POST', f'/api/v2/chat/completions?chat_id={session}', payload, True)
        self._check(rid, q, status, ctype, short)
        if 'application/json' in ctype:
            parse_json_reply(self._collect(rid, q, 65536), logger, short)
            raise BackendError('Qwen did not return a stream; the private API may have changed.')
        state = QwenStreamState(logger); lines = LineSplitter(); finished = False
        try:
            while not finished:
                event = self._get(rid, q, self.timeout)
                if event is None:
                    raise BackendError('The connection was interrupted during streaming (no data before the timeout).')
                kind = event.get('kind')
                if kind == 'error': self._raise_bridge_error(event)
                if kind == 'end':
                    pending = lines.flush(); finished = True
                elif kind == 'data':
                    pending = lines.feed(event.get('text') or '')
                else: continue
                for line in pending:
                    for chunk in state.feed(line): yield chunk
                    if state.done: finished = True; break
        except BaseException:
            self.bridge.abort(rid); raise
        if not state.done or kind != 'end': self.bridge.abort(rid)
        for chunk in state.flush(): yield chunk
        yield finish_stream(state, logger)

    def continue_answer(self, session, message_id, auto_continue=True, existing_text=''):
        """Qwen has no server-side 'continue': send a follow-up in the same chat (parent = the cut-off reply) asking the
        model to continue from the exact point where it stopped. Only runs when the user presses «ادامهٔ پاسخ»."""
        logger.info('qwen continue_requested')
        yield from self.stream(session, CONTINUE_PROMPT, message_id, False, False)
