"""Transport-independent pieces of the unofficial chat.qwen.ai web protocol.

Shared by the direct HTTP adapter (``qwen_adapter.QwenAdapter``) and the
built-in browser transport (``qwen_browser_transport.QwenBrowserAdapter``):
request payloads, error-envelope mapping, HTML/WAF detection and the
phase-based SSE parser. Nothing here performs network I/O.

Protocol (observed in open-source clients such as gpt4free's Qwen provider,
Qwen-Reverse and OmniRoute's qwen-web executor, November 2026):

1. POST /api/v2/chats/new                    -> {"success": true, "data": {"id": <chat_id>}}
2. POST /api/v2/chat/completions?chat_id=... -> SSE stream of ``data: {...}`` lines
   * ``{"response.created": {"chat_id", "parent_id", "response_id"}}`` first;
     ``response_id`` is the assistant message id and becomes the next turn's
     ``parent_id`` (multi-turn context lives on Qwen's server).
   * ``{"choices": [{"delta": {"phase", "content", "status", "extra"}}]}`` with
     phase ``think`` / ``thinking_summary`` (reasoning) or ``answer`` / null (text).
   * Errors arrive as ``{"error": ...}`` / ``{"success": false, "data": {"code"}}``
     or, from Alibaba's WAF, as an HTML captcha page or ``ret: [FAIL_SYS_USER_VALIDATE...]``.
"""
from app.i18n import tr
import json, time, uuid
from .deepseek_adapter import BackendError

QWEN_BASE = 'https://chat.qwen.ai'
QWEN_SPA_VERSION = '0.3.26'
QWEN_DEFAULT_MODEL = 'qwen3.7-plus'
# Live anonymous /api/models listing on 20 Nov 2026 returned qwen3.7-plus and
# qwen3.8-max; qwen3-coder-plus is listed by several open-source clients.
QWEN_FALLBACK_MODELS = ['qwen3.7-plus', 'qwen3.8-max', 'qwen3-coder-plus']

class QwenVerificationRequired(BackendError):
    """The user must log in or complete a verification/captcha themselves in a browser."""

def qwen_shape(value, depth=0):
    """Allowlisted protocol structure only: no values, ids, or arbitrary server keys."""
    if depth > 3: return '...'
    if isinstance(value, list): return [qwen_shape(value[0], depth + 1)] if value else []
    if not isinstance(value, dict): return type(value).__name__
    result = {}
    for key in ('success', 'code', 'data', 'error', 'ret', 'id', 'choices', 'delta', 'phase', 'status',
                'response.created', 'response_id', 'chat_id', 'parent_id', 'finish_reason', 'done', 'usage'):
        if key in value:
            result[key] = qwen_shape(value[key], depth + 1)
    return result

def error_code(obj):
    """Return a short error code string from a Qwen error envelope, or None."""
    if not isinstance(obj, dict): return None
    ret = obj.get('ret')
    if isinstance(ret, list) and any(isinstance(x, str) and ('FAIL_SYS_USER_VALIDATE' in x or 'RGV587' in x) for x in ret):
        return 'WAF'
    error = obj.get('error')
    if isinstance(error, str) and error: return 'ERROR:' + error[:200]
    if isinstance(error, dict):
        return str(error.get('code') or error.get('errorCode') or 'QwenError') + ':' + str(error.get('details') or error.get('message') or '')[:200]
    data = obj.get('data')
    if obj.get('success') is False or (isinstance(data, dict) and data.get('code')):
        if isinstance(data, dict):
            return str(data.get('code') or 'QwenError') + ':' + str(data.get('details') or data.get('message') or '')[:200]
        return 'QwenError:'
    return None

WAF_MESSAGE = ('Qwen web firewall (Alibaba WAF) verification required (captcha/slider). Complete it yourself in the '
               'built-in browser window, then retry. This app never solves captchas or copies browser cookies.')
TOKEN_MESSAGE = 'Your Qwen session token is invalid or expired. Log in again in the built-in browser or update the token in Settings.'
MANUAL_TOKEN_EXPIRED = ('The Qwen token saved in Settings has expired (Qwen web tokens are valid for only about 15 minutes). '
                        'Remove it in Settings and use the built-in browser login instead.')

# --- redaction ------------------------------------------------------------------
import re as _re
_REDACTIONS = [
    (_re.compile(r'eyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]*'), '<jwt>'),
    (_re.compile(r'(?i)(bearer\s+)[^\s"\',]+'), r'\1<redacted>'),
    (_re.compile(r'(?i)("?(?:token|access_token|refresh_token|authorization|cookie|set-cookie|password|secret)"?\s*[:=]\s*)"[^"]*"'), r'\1"<redacted>"'),
    (_re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '<email>'),
    (_re.compile(r'[A-Za-z0-9_\-+/=]{40,}'), '<long>'),
]

def redact(text, limit=300):
    """Best-effort removal of secrets (JWTs, bearer tokens, cookies, emails, long opaque strings)."""
    if isinstance(text, (bytes, bytearray)): text = text[:limit * 4].decode('utf-8', 'replace')
    text = str(text or '')[:limit * 4]
    for pattern, replacement in _REDACTIONS: text = pattern.sub(replacement, text)
    text = ' '.join(text.split())
    return text[:limit]

def token_expiry(token):
    """``exp`` claim (unix seconds) of a JWT-shaped token, or None. Only the claim is read; nothing is logged."""
    import base64
    try:
        part = (token or '').split('.')[1]; part += '=' * (-len(part) % 4)
        exp = json.loads(base64.urlsafe_b64decode(part.encode('ascii'))).get('exp')
        return int(exp) if isinstance(exp, (int, float)) else None
    except Exception:
        return None

def token_expired(token, now=None, margin=0):
    exp = token_expiry(token)
    return exp is not None and exp <= (time.time() if now is None else now) + margin

# --- error-code mapping ---------------------------------------------------------
AUTH_CODES = {'unauthorized', '401', 'tokenexpired', 'token_expired', 'invalidtoken', 'invalid_token', 'notlogin', 'not_login',
              'needlogin', 'need_login', 'loginrequired', 'login_required', 'unauthenticated', 'authenticationerror',
              'sessionexpired', 'session_expired', 'fail_sys_session_expired', 'fail_sys_token_expired'}
AUTH_PHRASES = ('token has expired', 'token expired', 'session has expired', 'session expired', 'invalid token', 'token is invalid',
                'token is no longer valid', 'please log in', 'please login', 'not logged in', 'log in again', 'login again',
                'login required', 'unauthorized')
RATE_CODES = ('ratelimit', 'rate_limit', 'ratelimited', 'parallellimited', 'quotalimited', 'quota_limited', 'toomanyrequests',
              'too_many_requests', 'requestlimited', '429')
RATE_PHRASES = ('rate limit', 'too many requests', 'too frequent', 'daily limit', 'usage limit', 'quota exceeded')

def split_code(code):
    head, _, details = str(code or '').partition(':')
    return head.strip(), details.strip()

def server_suffix(head, details):
    text = head if not details else f'{head}: {details}'
    return f' [Qwen server: {redact(text, 200)}]' if text else ''

def classify_code(code):
    """Return the mapper branch for a Qwen error code: waf/auth/rate/not_found/model/other."""
    head, details = split_code(code); h = head.lower().replace('-', '_'); hd = h.replace('_', ''); d = details.lower()
    if code == 'WAF' or any(m in str(code) for m in ('FAIL_SYS_USER_VALIDATE', 'RGV587', 'punish', 'x5sec')): return 'waf'
    if h in AUTH_CODES or hd in AUTH_CODES or any(p in d for p in AUTH_PHRASES): return 'auth'
    if any(m in h or m in hd for m in RATE_CODES) or any(p in d for p in RATE_PHRASES): return 'rate'
    if 'model' in h or 'model not' in d or 'invalid model' in d or 'unsupported model' in d: return 'model'
    if 'not_found' in h or 'notfound' in hd or 'chat not exist' in d or 'chat not found' in d: return 'not_found'
    return 'other'

def raise_for_code(code, logger=None, path=''):
    """Translate a Qwen error code (``HEAD:details``) into a BackendError that carries the server code/details.

    Only genuine authentication codes ask the user to log in again; everything else reports the server's own
    code and message so the UI can show it.
    """
    branch = classify_code(code); head, details = split_code(code); suffix = server_suffix(head, details)
    if logger: logger.info('qwen request=%s error_code=%s mapper=%s details=%s', path, redact(head, 60), branch, redact(details, 200))
    if branch == 'waf': raise QwenVerificationRequired(WAF_MESSAGE + suffix)
    if branch == 'auth': raise QwenVerificationRequired(TOKEN_MESSAGE + suffix)
    if branch == 'rate': raise BackendError('Qwen rate limit reached. Wait before retrying.' + suffix)
    if branch == 'not_found': raise BackendError('Qwen no longer has this remote chat session ID. Clear this conversation or start a new chat.' + suffix)
    if branch == 'model': raise BackendError('Qwen rejected the selected model. Pick another model in Settings (use "refresh model list").' + suffix)
    raise BackendError('Qwen rejected the request.' + suffix)

def html_kind(body):
    text = body[:20000].decode('utf-8', 'replace').lower() if isinstance(body, (bytes, bytearray)) else str(body)[:20000].lower()
    if 'not available in your region' in text: return 'region'
    if any(m in text for m in ('aliyun_waf', 'aliyuncaptcha', 'baxia', 'punish', 'x5sec', 'rgv587', 'nocaptcha', 'slide to verify')): return 'waf'
    return 'html'

def raise_html(body, status):
    kind = html_kind(body)
    if kind == 'region':
        raise BackendError(f'Qwen is not available in your region (HTTP {status}). chat.qwen.ai blocks this network/IP; a system-wide VPN is required.')
    if kind == 'waf':
        raise QwenVerificationRequired(WAF_MESSAGE)
    raise QwenVerificationRequired(f'Qwen returned an unexpected web page (HTTP {status}) instead of API data; a login, Cloudflare/WAF verification may be required, or the private API may have changed.')

def raise_for_status(status, content_type, read_body, logger=None, path=''):
    """Shared HTTP status / content-type checks. ``read_body`` lazily returns bytes."""
    if 'text/html' in (content_type or ''):
        body = read_body()
        if logger: logger.info('qwen request=%s status=%s html_kind=%s body_head=%s', path, status, html_kind(body), redact(body, 300))
        raise_html(body, status)
    if status == 200: return
    code = None; body = b''
    try:
        body = read_body()
        if logger: logger.info('qwen request=%s status=%s error_body=%s', path, status, redact(body, 300))
        obj = json.loads(body)
        if logger: logger.info('qwen request=%s error_shape=%s', path, qwen_shape(obj))
        code = error_code(obj)
    except (ValueError, TypeError, AttributeError): pass
    if status == 401:
        head, details = split_code(code) if code else ('HTTP 401', '')
        if logger: logger.info('qwen request=%s error_code=%s mapper=auth details=%s', path, redact(head, 60), redact(details, 200))
        raise QwenVerificationRequired(TOKEN_MESSAGE + server_suffix(head if code else 'HTTP 401', details))
    if status == 429:
        if logger: logger.info('qwen request=%s mapper=rate', path)
        raise BackendError('Qwen rate limit reached. Wait before retrying.' + (server_suffix(*split_code(code)) if code else ' [Qwen server: HTTP 429]'))
    if status == 403 and not (code and classify_code(code) in ('auth', 'rate')):
        if logger: logger.info('qwen request=%s mapper=forbidden', path)
        raise QwenVerificationRequired('Qwen denied access (HTTP 403): Cloudflare/WAF verification required or the account is restricted.'
                                       + (server_suffix(*split_code(code)) if code else ''))
    if code: raise_for_code(code, logger, path)
    if logger: logger.info('qwen request=%s mapper=http_status', path)
    if status >= 500: raise BackendError(f'Qwen service is unavailable. Try again later. [Qwen server: HTTP {status}]')
    raise BackendError(f'Qwen returned HTTP {status}; its private API may have changed. [Qwen server: HTTP {status}]')

def parse_json_reply(body, logger=None, path=''):
    try: obj = json.loads(body)
    except (ValueError, TypeError) as e: raise BackendError('Invalid Qwen server response; the private API may have changed.') from e
    if logger: logger.info('qwen request=%s response_shape=%s', path, qwen_shape(obj))
    if not isinstance(obj, dict): raise BackendError('Invalid JSON response structure from Qwen; the private API may have changed.')
    code = error_code(obj)
    if code:
        if logger: logger.info('qwen request=%s error_body=%s', path, redact(body, 300))
        raise_for_code(code, logger, path)
    return obj

def new_chat_payload(model):
    return {'title': 'New Chat', 'models': [model], 'chat_mode': 'normal', 'chat_type': 't2t',
            'timestamp': int(time.time() * 1000), 'project_id': ''}

def chat_id_from(obj):
    data = obj.get('data')
    chat_id = data.get('id') if isinstance(data, dict) else None
    if not isinstance(chat_id, str) or not chat_id:
        raise BackendError('Qwen chat creation succeeded but returned no session ID. The private API may have changed; see sanitized diagnostics.log.')
    return chat_id

def models_from(obj):
    models = []
    for m in obj.get('data') or []:
        if not isinstance(m, dict) or not isinstance(m.get('id'), str): continue
        info = m.get('info') if isinstance(m.get('info'), dict) else {}
        meta = info.get('meta') if isinstance(info.get('meta'), dict) else {}
        types = meta.get('chat_type')
        if not types or 't2t' in types: models.append(m['id'])
    if not models: raise BackendError('Qwen returned no chat models; the private API may have changed.')
    return models

def check_parent(parent):
    if parent is None: return None
    parent = str(parent).strip()
    if not parent or len(parent) > 200: raise BackendError('Invalid saved remote parent message ID. Start a new chat or clear this conversation.')
    return parent

INLINE_CODE_INSTRUCTION = ('[Formatting note for this reply: never use your built-in tools (no code interpreter, artifacts or canvas) and do not run code yourself. '
                           'If and only if the user asks for code or the answer genuinely requires code, write the complete code directly in '
                           'this reply inside fenced Markdown code blocks (```language ... ```), without shortening or omitting parts. '
                           'For greetings and normal conversation answer normally in plain text, without any code. Do not mention this note.]')
CONTINUE_PROMPT = ('Continue exactly from where your previous reply stopped. Do not repeat anything already written and do not add '
                   'an introduction. If you stopped inside a code block, continue the code from the exact next character inside the '
                   'same code block (do not open a new fence) and close the block when the code is complete.')

def chat_payload(model, session, prompt, parent=None, thinking=False, search=False, inline_code=False):
    """Payload for /api/v2/chat/completions. With ``inline_code`` the code interpreter / tools / plugins are switched off
    and a short instruction asks the model to write all code as fenced blocks in the reply itself."""
    fid = str(uuid.uuid4()); now = int(time.time() * 1000)
    if thinking:
        feature = {'thinking_enabled': True, 'auto_thinking': False, 'thinking_mode': 'Thinking', 'thinking_format': 'summary',
                   'output_schema': 'phase', 'research_mode': 'normal', 'auto_search': bool(search)}
    else:
        feature = {'thinking_enabled': False, 'auto_thinking': False, 'thinking_mode': 'Fast', 'output_schema': 'phase',
                   'research_mode': 'normal', 'auto_search': bool(search)}
    if inline_code:
        feature.update(code_interpreter=False, function_calling=False, plugins_enabled=bool(search))
        prompt = INLINE_CODE_INSTRUCTION + '\n\n' + prompt
    chat_type = 'search' if search else 't2t'
    return {'stream': True, 'version': '2.1', 'incremental_output': True, 'chat_id': session, 'chat_mode': 'normal',
            'model': model, 'parent_id': parent, 'timestamp': now,
            'messages': [{'fid': fid, 'parentId': parent, 'childrenIds': [], 'role': 'user', 'content': prompt,
                          'user_action': 'chat', 'files': [], 'timestamp': now, 'models': [model],
                          'chat_type': chat_type, 'feature_config': feature,
                          'extra': {'meta': {'subChatType': chat_type}}, 'sub_chat_type': chat_type, 'parent_id': parent}]}

def finish_stream(state, logger=None):
    """Final checks after the stream ends; returns the 'complete' (or 'incomplete' when Qwen hit its length limit) chunk."""
    if logger:
        logger.info('qwen stream finished_marker=%s message_id_present=%s text_chars=%s thinking_chars=%s finish_reason=%s tools=%s phases=%s',
                    state.finished, state.message_id is not None, len(state.text), len(state.thinking), state.finish_reason,
                    state.tool_count, ','.join(sorted(state.phases)))
    if state.html: raise_html(state.html, 200)
    if not state.text:
        raise BackendError('Qwen stream ended without an answer; the private API may have changed or the request was blocked.')
    kind = 'incomplete' if state.finish_reason == 'length' else 'complete'
    return {'type': kind, 'content': '', 'message_id': state.message_id}

_PHASE_NAME = __import__('re').compile(r'[^A-Za-z0-9_.-]')
_HTML_IN_STRING = __import__('re').compile(r"(\'\'\'|\"\"\")\s*(<(?:!DOCTYPE|html)[\s\S]*?)\1", __import__('re').I)
THINK_PHASES = ('think', 'reasoning', 'DeepThinking', 'image_gen_think', 'ResearchPlanning')
ANSWER_PHASES = (None, 'answer', 'ReportGeneration', 'slides')
TOOL_PHASES = ('tool_call', 'tool', 'tool_result', 'function', 'function_call', 'code_interpreter', 'code', 'plugin', 'artifacts', 'code_execution')
QUIET_PHASES = ('KeepAlive', 'web_search', 'web_extract', 'search')

def _fence(lang, body):
    body = body.replace('```', '`\u200b``').rstrip('\n')
    return f'\n\n```{lang}\n{body}\n```\n'

def _merge(old, piece):
    """Tool fields arrive either as cumulative snapshots or as increments."""
    if not piece: return old
    if old and piece.startswith(old): return piece
    return old + piece


class QwenStreamState:
    """Parses Qwen's phase-based SSE lines into the app's chunk dictionaries.

    Tool use (code interpreter etc.) is not dropped: the tool's code/arguments and output are collected and emitted
    as fenced code blocks in the answer text once the tool phase ends.
    """
    def __init__(self, logger=None):
        self.logger = logger
        self.message_id = None; self.text = ''; self.thinking = ''; self.summary = ''
        self.finished = False; self.done = False; self.html = b''
        self.finish_reason = None; self.phases = set(); self.tool = None; self.tool_count = 0

    def _chunk(self, kind, content):
        return {'type': kind, 'content': content, 'message_id': self.message_id}

    def _note_phase(self, phase):
        name = _PHASE_NAME.sub('', str(phase))[:40] if phase is not None else 'none'
        if name not in self.phases:
            self.phases.add(name)
            known = phase in ANSWER_PHASES or phase in THINK_PHASES or phase in TOOL_PHASES or phase in QUIET_PHASES or phase == 'thinking_summary'
            if self.logger and not known: self.logger.info('qwen stream unknown_phase=%s', name)

    def _tool_feed(self, phase, delta, content):
        if self.tool is None:
            self.tool = {'name': '', 'args': '', 'output': ''}; self.tool_count += 1
        fc = delta.get('function_call') if isinstance(delta.get('function_call'), dict) else {}
        extra = delta.get('extra') if isinstance(delta.get('extra'), dict) else {}
        name = fc.get('name') or extra.get('tool_name')
        if not name and not self.tool['name'] and phase not in ('tool_call', 'function', 'function_call', 'tool', 'tool_result'): name = phase
        if name: self.tool['name'] = str(name)[:60]
        args = fc.get('arguments')
        if isinstance(args, (dict, list)): args = json.dumps(args, ensure_ascii=False)
        if isinstance(args, str):
            try: complete = isinstance(json.loads(args), (dict, list))
            except ValueError: complete = False
            # a complete JSON document is a snapshot of all arguments so far; anything else is an increment
            self.tool['args'] = args if complete else _merge(self.tool['args'], args)
        if isinstance(content, str) and content:
            if delta.get('role') == 'function' or phase in ('tool_result', 'function'):
                self.tool['output'] = _merge(self.tool['output'], content)
            elif not args:
                self.tool['args'] = _merge(self.tool['args'], content)
        result = extra.get('tool_result')
        if isinstance(result, str) and result: self.tool['output'] = _merge(self.tool['output'], result)

    def flush(self):
        """Emit a pending tool call as fenced code blocks (called when the tool phase ends and at stream end)."""
        tool, self.tool = self.tool, None
        if not tool or not (tool['args'] or tool['output']): return []
        code = tool['args']
        try:
            obj = json.loads(code)
            if isinstance(obj, dict):
                for key in ('code', 'source', 'script', 'content', 'input', 'query'):
                    if isinstance(obj.get(key), str): code = obj[key]; break
        except (ValueError, TypeError): pass
        name = tool['name'] or 'tool'
        lang = 'python' if any(k in name.lower() for k in ('code', 'python', 'interpreter')) else ''
        parts = [tr('\n\n**ابزار Qwen: {name}**', name=name)]
        if code: parts.append(_fence(lang, code))
        for match in _HTML_IN_STRING.finditer(code or ''):
            parts.append(tr('\n**HTML داخل کد بالا:**') + _fence('html', match.group(2)))
        if tool['output']: parts.append(tr('\n**خروجی ابزار:**') + _fence('text', tool['output']))
        text = ''.join(parts)
        self.text += text
        if self.logger: self.logger.info('qwen stream tool_flushed name=%s code_chars=%s output_chars=%s', _PHASE_NAME.sub('', name)[:40], len(code or ''), len(tool['output']))
        return [self._chunk('text', text)]

    def feed(self, line):
        if not line: return []
        if isinstance(line, str): line = line.encode('utf-8')
        stripped = line.strip()
        if not stripped: return []
        if stripped.startswith(b'<') or (self.html and not stripped.startswith(b'data:')):
            self.html += stripped[:2000]; self.done = len(self.html) > 4000
            return []
        if stripped.startswith(b'data:'): payload = stripped[5:].strip()
        elif stripped.startswith(b'{'): payload = stripped
        else: return []
        if payload == b'[DONE]': self.done = True; self.finished = True; return []
        try: obj = json.loads(payload)
        except ValueError as e: raise BackendError('Invalid Qwen streaming response; the private API may have changed.') from e
        if not isinstance(obj, dict): return []
        code = error_code(obj)
        if code: raise_for_code(code, self.logger, 'stream')
        created = obj.get('response.created')
        if isinstance(created, dict) and created.get('response_id'):
            self.message_id = str(created['response_id'])
        elif obj.get('response_id') and not self.message_id:
            self.message_id = str(obj['response_id'])
        if obj.get('done') is True or 'response.stopped' in obj:
            self.done = True; self.finished = True
        choices = obj.get('choices') or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        delta = choice.get('delta') or choice.get('message') or {}
        if not isinstance(delta, dict): return []
        phase = delta.get('phase'); status = delta.get('status'); content = delta.get('content')
        extra = delta.get('extra') if isinstance(delta.get('extra'), dict) else {}
        if choice.get('finish_reason'): self.finish_reason = str(choice['finish_reason'])[:30]
        if status == 'error':
            raise BackendError('Qwen reported an error while generating the response; the private API may have changed.')
        if phase is not None or delta: self._note_phase(phase)
        result = []
        if phase == 'KeepAlive': return []
        is_tool = phase in TOOL_PHASES or delta.get('role') == 'function' or isinstance(delta.get('function_call'), dict)
        if is_tool:
            self._tool_feed(phase, delta, content)
            if status == 'finished' and phase not in ('tool_call', 'function_call') and self.tool and self.tool['output']:
                result.extend(self.flush())
            if choice.get('finish_reason') in ('stop', 'length'): self.finished = True
            return result
        if self.tool is not None and (phase in ANSWER_PHASES or phase in THINK_PHASES or phase == 'thinking_summary'):
            result.extend(self.flush())
        if phase == 'thinking_summary':
            thought = extra.get('summary_thought') or extra.get('summary_content') or {}
            value = thought.get('content', []) if isinstance(thought, dict) else thought
            snapshot = '\n'.join(v for v in value if isinstance(v, str)) if isinstance(value, list) else value
            if isinstance(snapshot, str) and snapshot and snapshot != self.summary:
                added = snapshot[len(self.summary):] if snapshot.startswith(self.summary) else '\n' + snapshot
                self.summary = snapshot; self.thinking += added; result.append(self._chunk('thinking', added))
            elif isinstance(content, str) and content:
                self.thinking += content; result.append(self._chunk('thinking', content))
        elif phase in THINK_PHASES:
            if isinstance(content, str) and content:
                self.thinking += content; result.append(self._chunk('thinking', content))
        elif phase in ANSWER_PHASES:
            if isinstance(content, str) and content:
                self.text += content; result.append(self._chunk('text', content))
            if phase == 'answer' and status == 'finished': self.finished = True
        if choice.get('finish_reason') in ('stop', 'length'): self.finished = True
        return result


class LineSplitter:
    """Reassembles SSE lines from arbitrary text chunks (browser ReadableStream pieces)."""
    def __init__(self): self.buffer = ''
    def feed(self, text):
        self.buffer += text
        parts = self.buffer.split('\n')
        self.buffer = parts.pop()
        return [p.rstrip('\r') for p in parts]
    def flush(self):
        rest, self.buffer = self.buffer, ''
        return [rest.rstrip('\r')] if rest.strip() else []
