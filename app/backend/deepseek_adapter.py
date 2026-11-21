"""Adapter for DeepSeek4Free's documented private endpoints and WASM solver."""
import json, threading, logging, os, time
from pathlib import Path
from logging.handlers import RotatingFileHandler
from curl_cffi import requests
from dsk.pow import DeepSeekPOW
from .streaming import StreamState

class BackendError(Exception): pass
class Cancelled(Exception): pass

logger = logging.getLogger('deepseek_desktop.backend')
if not logger.handlers:
    try:
        folder = Path(os.environ['LOCALAPPDATA']) / 'DeepSeekDesktop'
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / 'diagnostics.log', maxBytes=200_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    except (OSError, KeyError):
        logger.addHandler(logging.NullHandler())

def shape(value):
    """Allowlisted protocol structure only: no values or arbitrary server keys."""
    if not isinstance(value, dict): return type(value).__name__
    result = {}
    for key in ('code', 'msg', 'data', 'biz_code', 'biz_msg', 'biz_data', 'chat_session', 'id', 'challenge', 'choices'):
        if key in value:
            result[key] = shape(value[key])
    return result

class Adapter:
    BASE = 'https://chat.deepseek.com/api/v0'
    def __init__(self, token, timeout=60, cancel=None):
        self.token = token.strip()
        if not self.token: raise BackendError('Enter a DeepSeek web session token in Settings.')
        self.timeout = timeout
        self.cancel = cancel or threading.Event()
        self.pow = DeepSeekPOW()
    def headers(self, proof=None):
        h = {'authorization':'Bearer '+self.token, 'content-type':'application/json', 'accept':'*/*', 'origin':'https://chat.deepseek.com', 'referer':'https://chat.deepseek.com/', 'x-app-version':'20241129.1', 'x-client-platform':'web', 'x-client-version':'1.0.0-always', 'x-client-locale':'en_US'}
        if proof: h['x-ds-pow-response'] = proof
        return h
    def request(self, path, data, proof=None, stream=False):
        if self.cancel.is_set(): raise Cancelled()
        logger.info('request_start path=%s streaming=%s',path,stream)
        try:
            r = requests.post(self.BASE+path, headers=self.headers(proof), json=data, impersonate='chrome120', timeout=self.timeout, stream=stream)
        except requests.exceptions.RequestException as e:
            raise BackendError('Network connection failed or timed out. Please retry.') from e
        status = r.status_code
        content_type = getattr(r, 'headers', {}).get('content-type', 'unknown').split(';', 1)[0].lower()
        logger.info('request=%s status=%s content_type=%s', path, status, content_type)
        if status != 200:
            if status == 422:
                try:
                    body = r.content[:4096]
                    error = json.loads(body)
                    logger.info('request=%s validation_shape=%s', path, shape(error))
                    validation_code = error.get('code') if isinstance(error, dict) else None
                except (ValueError, TypeError, AttributeError):
                    logger.info('request=%s validation_body_type=non_json body_bytes=%s', path, len(getattr(r, 'content', b'')))
                    validation_code = None
                r.close()
                raise BackendError(f'DeepSeek rejected the conversation context (HTTP 422, code {validation_code}). The saved remote parent message ID or private request schema is invalid.')
            r.close()
            if status == 401: raise BackendError('Your session token is invalid or expired. Update it in Settings.')
            if status == 429: raise BackendError('DeepSeek rate limit reached. Wait before retrying.')
            if status == 403: raise BackendError('Access denied or Cloudflare verification required. Sign in on the DeepSeek website and try again; this app cannot transfer a browser challenge.')
            if status >= 500: raise BackendError('DeepSeek service is unavailable. Try again later.')
            raise BackendError(f'DeepSeek returned HTTP {status}; its private API may have changed.')
        if 'text/html' in r.headers.get('content-type','').lower():
            r.close(); raise BackendError('Cloudflare verification or an unexpected web page was returned. Sign in on the DeepSeek website.')
        return r
    def json_request(self, path, data):
        r = self.request(path,data)
        try:
            obj = r.json()
            logger.info('request=%s response_shape=%s', path, shape(obj))
            if not isinstance(obj, dict): raise BackendError('Invalid JSON response structure; the private API may have changed.')
            code = obj.get('code')
            if code in (40003, 401, 40101): raise BackendError('Your DeepSeek web session token is invalid or expired. Update it in Settings.')
            if code in (429, 42900): raise BackendError('DeepSeek rate limit reached. Wait before retrying.')
            if code != 0: raise BackendError('DeepSeek rejected the request or changed its private API. Check diagnostics.log for the sanitized response shape.')
            return obj
        except (ValueError, AttributeError) as e: raise BackendError('Invalid server response; the private API may have changed.') from e
        finally: r.close()
    def create_session(self):
        obj = self.json_request('/chat_session/create', {'character_id':None})
        data = obj.get('data')
        biz = data.get('biz_data') if isinstance(data, dict) else None
        if isinstance(data, dict) and data.get('biz_code') not in (None, 0):
            raise BackendError('DeepSeek rejected session creation. The session may have expired or the private API may have changed.')
        nested = biz.get('chat_session') if isinstance(biz, dict) else None
        session_id = nested.get('id') if isinstance(nested, dict) else (biz.get('id') if isinstance(biz, dict) else None)
        if not isinstance(session_id, (str, int)) or not str(session_id):
            raise BackendError('Session creation succeeded but returned no session ID in the DeepSeek4Free response structure. The private API may have changed; see sanitized diagnostics.log.')
        return str(session_id)
    def stream(self, session, prompt, parent=None, thinking=False, search=False, auto_continue=True):
        # SQLite stores identifiers as TEXT; the web API emits numeric message IDs.
        if parent is not None:
            if isinstance(parent, bool) or not str(parent).isdigit():
                raise BackendError('Invalid saved remote parent message ID. Start a new chat or clear this conversation.')
            parent = int(parent)
        try:
            challenge = self.json_request('/chat/create_pow_challenge', {'target_path':'/api/v0/chat/completion'})['data']['biz_data']['challenge']
            proof = self.pow.solve_challenge(challenge)
        except (KeyError, TypeError, ValueError) as e: raise BackendError('Unexpected proof-of-work response; the private API may have changed.') from e
        payload = {'chat_session_id':session,'parent_message_id':parent,'prompt':prompt,'ref_file_ids':[],'thinking_enabled':thinking,'search_enabled':search}
        yield from self._answer(session, '/chat/completion', payload, proof, auto_continue=auto_continue)

    def continue_answer(self, session, message_id, auto_continue=True, existing_text=''):
        if isinstance(message_id, bool) or not str(message_id).isdigit():
            raise BackendError('A valid remote response message ID is required to continue.')
        payload = {'chat_session_id':session,'message_id':int(message_id),'fallback_to_resume':True}
        yield from self._answer(session, '/chat/continue', payload, None, auto_continue, existing_text)

    def _answer(self, session, endpoint, payload, proof, auto_continue, existing_text=''):
        state = StreamState()
        attempts = 0
        replay_prefix = existing_text
        while True:
            response = self.request(endpoint, payload, proof, True)
            if 'application/json' in getattr(response,'headers',{}).get('content-type',''):
                try:
                    envelope = response.json(); data = envelope.get('data') or {}
                    code = data.get('biz_code') if isinstance(data,dict) else None
                except (ValueError, AttributeError): code = None
                finally: response.close()
                raise BackendError(f'DeepSeek continuation did not return a stream (business code {code}). The response may already be complete.')
            state.closed = False
            try:
                for line in response.iter_lines():
                    if self.cancel.is_set(): raise Cancelled()
                    for chunk in state.feed(line):
                        if replay_prefix and chunk['content']:
                            content = chunk['content']
                            if replay_prefix.startswith(content):
                                replay_prefix = replay_prefix[len(content):]
                                continue
                            if content.startswith(replay_prefix):
                                chunk = dict(chunk, content=content[len(replay_prefix):])
                                replay_prefix = ''
                            else:
                                replay_prefix = ''
                        if chunk['content']: yield chunk
            except requests.exceptions.RequestException as e:
                raise BackendError('The connection was interrupted during streaming.') from e
            except ValueError as e:
                raise BackendError('Invalid streaming response; the private API may have changed.') from e
            finally: response.close()
            logger.info('stream endpoint=%s status=%s closed=%s message_id_present=%s', endpoint, state.status, state.closed, state.message_id is not None)
            if state.status == 'INCOMPLETE':
                if not state.message_id: raise BackendError('DeepSeek stopped an incomplete response without a message ID.')
                yield {'type':'incomplete','content':'','message_id':state.message_id}
                if not auto_continue or attempts >= 3: return
                attempts += 1
                if self.cancel.wait(min(attempts,3)): raise Cancelled()
                endpoint = '/chat/continue'
                payload = {'chat_session_id':session,'message_id':int(state.message_id),'fallback_to_resume':True}
                proof = None
                state.status = None
                continue
            if state.status in ('FINISHED','COMPLETED'):
                yield {'type':'complete','content':'','message_id':state.message_id}
                return
            raise BackendError('DeepSeek stream ended without a completion status.')
