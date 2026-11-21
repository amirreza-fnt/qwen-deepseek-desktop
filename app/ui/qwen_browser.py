"""Built-in Qwen browser (QtWebEngine) and the GUI-thread side of the browser transport.

The user logs in to https://chat.qwen.ai and completes any captcha/verification
*themselves* in this window. The app never solves captchas, never generates
anti-bot signatures and never reads or exports cookies: API requests are made by
``window.fetch`` inside the page itself (main world, ``credentials: 'include'``),
so the site's own cookies and scripts apply exactly as in a normal browser.
Response text is collected in the page and polled from Python with
``runJavaScript`` as a JSON string (no QWebChannel object is exposed to the
site's scripts).
Profile data (cookies, localStorage, cache) is kept on disk under
``%LOCALAPPDATA%\\DeepSeekDesktop\\qwen-web``.
"""
from app.i18n import tr, layout_direction, label_alignment, ui_dir, ui_align
import json, os, queue, re, threading, time, uuid
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QUrl, Qt, QThread, QCoreApplication, QEventLoop
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from app.backend.deepseek_adapter import logger
from app.backend.qwen_protocol import QWEN_BASE

def default_profile_path():
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'DeepSeekDesktop' / 'qwen-web'

START_JS = r"""
(function (spec) {
  var store = window.__deepseekDesktopQwen = window.__deepseekDesktopQwen || {};
  var st = {chunks: [], done: false, status: null, ctype: null, error: null, message: null, ctrl: new AbortController()};
  store[spec.id] = st;
  // The page's own token (kept fresh by the site) wins; the manual token is only a fallback.
  var token = null, source = 'page';
  try { token = window.localStorage.getItem('token'); } catch (e) { token = null; }
  if (token && token.charAt(0) === '"') { try { token = JSON.parse(token); } catch (e) {} }
  if (!token && spec.token) { token = spec.token; source = 'manual'; }
  if (!token) { st.error = 'NO_TOKEN'; st.done = true; return 'no-token'; }
  if (source === 'page' && !spec.allow_stale) {
    try {
      var p = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      var exp = JSON.parse(atob(p + '==='.slice((p.length + 3) % 4))).exp;
      var fp = token.slice(-12);
      if (typeof exp === 'number' && exp * 1000 < Date.now() + 15000) {
        // Remember which token was stale (sessionStorage survives the reload): right after the reload the
        // page may still hold this same token for a moment before its refresh finishes.
        try { window.sessionStorage.setItem('__dsd_stale_fp', fp); } catch (e) {}
        delete store[spec.id]; return 'stale-token';
      }
      var staleFp = null; try { staleFp = window.sessionStorage.getItem('__dsd_stale_fp'); } catch (e) {}
      if (staleFp && staleFp === fp) { delete store[spec.id]; return 'stale-token'; }
      if (staleFp) {
        // The site just replaced the stale token: give its refresh a moment to settle before using the
        // new one (a request sent immediately was observed to get 401 Unauthorized).
        try { window.sessionStorage.removeItem('__dsd_stale_fp'); window.sessionStorage.setItem('__dsd_fresh_at', String(Date.now())); } catch (e) {}
        delete store[spec.id]; return 'stale-token';
      }
      var freshAt = 0; try { freshAt = Number(window.sessionStorage.getItem('__dsd_fresh_at') || 0); } catch (e) {}
      if (freshAt && Date.now() - freshAt < 2500) { delete store[spec.id]; return 'stale-token'; }
      if (freshAt) { try { window.sessionStorage.removeItem('__dsd_fresh_at'); } catch (e) {} }
    } catch (e) {}
  }
  var headers = {};
  for (var k in spec.headers) { headers[k] = spec.headers[k]; }
  headers['authorization'] = 'Bearer ' + token;
  var init = {method: spec.method, headers: headers, credentials: 'include', signal: st.ctrl.signal};
  if (spec.body !== null) { init.body = spec.body; }
  window.fetch(spec.url, init).then(function (r) {
    st.status = r.status; st.ctype = r.headers.get('content-type') || '';
    if (!spec.stream || !r.body || st.ctype.indexOf('text/event-stream') < 0) {
      return r.text().then(function (t) { st.chunks.push(t.slice(0, spec.limit)); st.done = true; });
    }
    var reader = r.body.getReader(); var decoder = new TextDecoder();
    function pump() {
      return reader.read().then(function (res) {
        if (res.done) { var tail = decoder.decode(); if (tail) st.chunks.push(tail); st.done = true; return; }
        st.chunks.push(decoder.decode(res.value, {stream: true}));
        return pump();
      });
    }
    return pump();
  }).catch(function (e) {
    st.error = (e && e.name === 'AbortError') ? 'ABORTED' : 'NETWORK';
    st.message = String((e && e.name) || 'Error').slice(0, 60);
    st.done = true;
  });
  return 'started:' + source;
})(__SPEC__)
"""

POLL_JS = r"""
(function (id) {
  var store = window.__deepseekDesktopQwen; var st = store && store[id];
  if (!st) { return JSON.stringify({missing: true}); }
  var data = st.chunks.join(''); st.chunks = [];
  var out = {status: st.status, ctype: st.ctype, data: data, done: st.done, error: st.error, message: st.message};
  if (st.done) { delete store[id]; }
  return JSON.stringify(out);
})(__ID__)
"""

ABORT_JS = r"""
(function (id) { var store = window.__deepseekDesktopQwen; var st = store && store[id]; if (st && !st.done) { st.ctrl.abort(); } return true; })(__ID__)
"""

# Read-only check whether the site's own anti-bot layer shows a verification (slider/captcha) overlay; it holds the
# page's requests until a person completes it. Only a boolean leaves the page.
VERIFY_OVERLAY_JS = r"""
(function () {
  var sel = '[id*="baxia"],[class*="baxia"],[id*="aliyunCaptcha"],[class*="aliyunCaptcha"],.nc_wrapper,#nc_1_wrapper,iframe[src*="captcha"],iframe[src*="punish"]';
  var nodes = document.querySelectorAll(sel);
  for (var i = 0; i < nodes.length; i++) { var r = nodes[i].getBoundingClientRect(); if (r.width > 0 && r.height > 0) return true; }
  var dialogs = document.querySelectorAll('[role="dialog"],.ant-modal,.modal');
  for (var j = 0; j < dialogs.length; j++) { if (/drag the slider|complete the verification|\u0627\u0633\u0644\u0627\u06cc\u062f\u0631|\u9a8c\u8bc1/i.test((dialogs[j].innerText || '').slice(0, 400))) return true; }
  return false;
})()
"""

TOKEN_PRESENT_JS = "(function(){try{return !!window.localStorage.getItem('token');}catch(e){return false;}})()"


class _Page(QWebEnginePage):
    """Page that opens site pop-ups (e.g. OAuth login) in separate windows of the same profile."""
    def __init__(self, profile, parent=None):
        super().__init__(profile, parent); self.popups = []
    def createWindow(self, _type):
        popup = QDialog(); popup.setWindowTitle('Qwen'); popup.resize(900, 700)
        layout = QVBoxLayout(popup); view = QWebEngineView(popup); page = _Page(self.profile(), view); view.setPage(page); layout.addWidget(view)
        page.windowCloseRequested.connect(popup.close)
        popup.finished.connect(lambda *_: self.popups.remove(popup) if popup in self.popups else None)
        self.popups.append(popup); popup.show()
        return page


class QwenBrowser(QObject):
    """GUI-thread owner of the persistent QtWebEngine profile/page and the request bridge."""
    _start = Signal(str, str)
    _abort = Signal(str)
    state_changed = Signal()

    def __init__(self, base=QWEN_BASE, storage_path='default', parent=None):
        super().__init__(parent)
        self.base = base.rstrip('/')
        if storage_path == 'default': storage_path = default_profile_path()
        if storage_path:
            path = Path(storage_path); path.mkdir(parents=True, exist_ok=True)
            self.profile = QWebEngineProfile('qwen-web', self)
            self.profile.setPersistentStoragePath(str(path))
            self.profile.setCachePath(str(path / 'cache'))
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        else:
            self.profile = QWebEngineProfile(self)  # off-the-record (tests)
        # Plain Chromium user agent without the "QtWebEngine/x" token (login pages often reject it).
        self.profile.setHttpUserAgent(re.sub(r'\s*QtWebEngine/\S+', '', self.profile.httpUserAgent()))
        self.page = _Page(self.profile, self)
        self.page.loadStarted.connect(self._load_started)
        self.page.loadFinished.connect(self._load_finished)
        self.loaded = False; self.loading = False; self.last_load_ok = None
        self.requests = {}; self.pending = []; self.lock = threading.Lock()
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._poll)
        self._start.connect(self._on_start); self._abort.connect(self._on_abort)
        self.dialog = None

    # ----- bridge API (thread-safe) ---------------------------------------
    def submit(self, spec):
        rid = uuid.uuid4().hex; q = queue.Queue()
        with self.lock: self.requests[rid] = {'queue': q, 'spec': None, 'started': False, 'polling': False, 'meta': False}
        self._start.emit(rid, json.dumps(spec))
        return rid, q

    def abort(self, rid):
        self._abort.emit(rid)

    def pump(self):
        if QThread.currentThread() is self.thread():
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)

    # ----- page lifecycle --------------------------------------------------
    def ensure_loaded(self):
        if not self.loaded and not self.loading:
            self.loading = True; self.page.load(QUrl(self.base + '/'))

    def on_site(self):
        return self.page.url().host() == QUrl(self.base).host()

    def _load_started(self):
        self.loading = True; self.loaded = False; self.state_changed.emit()

    def _load_finished(self, ok):
        # An error page served by chat.qwen.ai itself (e.g. the HTTP 405 region block) reports ok=False
        # but is still on the site; API calls then return the precise error, so only off-site is fatal.
        self.loading = False; self.last_load_ok = bool(ok); self.loaded = bool(ok) or self.on_site()
        logger.info('qwen_browser load_finished ok=%s on_site=%s', bool(ok), self.on_site())
        pending, self.pending = self.pending, []
        for rid in pending:
            if self.loaded and self.on_site(): self._run(rid)
            else: self._fail(rid, 'LOAD_FAILED' if not self.loaded else 'NOT_ON_SITE')
        self.state_changed.emit()

    # ----- GUI-thread slots -------------------------------------------------
    @Slot(str, str)
    def _on_start(self, rid, spec_json):
        info = self.requests.get(rid)
        if info is None: return
        spec = json.loads(spec_json); spec['id'] = rid; info['spec'] = spec
        if self.loaded and not self.loading:
            if self.on_site(): self._run(rid)
            else: self._fail(rid, 'NOT_ON_SITE')
        else:
            self.pending.append(rid); self.ensure_loaded()

    def _run(self, rid):
        info = self.requests.get(rid)
        if info is None: return
        js = START_JS.replace('__SPEC__', json.dumps(info['spec']))
        def started(result, rid=rid):
            current = self.requests.get(rid)
            if current is None: return
            if result == 'stale-token':
                self._stale_token(rid, current); return
            if not (isinstance(result, str) and (result.startswith('started') or result == 'no-token')):
                self._fail(rid, 'PAGE_RELOADED'); return
            if result.startswith('started:'): logger.info('qwen_browser request_started token_source=%s', result.split(':', 1)[1])
            current['started'] = True; current['t0'] = time.monotonic()
            if not self.timer.isActive(): self.timer.start()
        self.page.runJavaScript(js, 0, started)

    def _stale_token(self, rid, info):
        """The page token is (about to be) expired: let the site refresh it by reloading the page once, then
        re-check for up to ~10 s. No request is sent with a stale token unless the refresh never happens."""
        attempt = info['stale'] = info.get('stale', 0) + 1
        logger.info('qwen_browser token_stale attempt=%s', attempt)
        if attempt == 1:
            self.pending.append(rid); self.loaded = False; self.loading = True
            self.page.triggerAction(QWebEnginePage.WebAction.Reload)
        elif attempt <= 10:
            QTimer.singleShot(1000, lambda rid=rid: self._run(rid))
        else:
            info['spec']['allow_stale'] = True; self._run(rid)

    def _poll(self):
        if not self.requests: self.timer.stop(); return
        for rid, info in list(self.requests.items()):
            if info['started'] and not info['polling']:
                info['polling'] = True
                self.page.runJavaScript(POLL_JS.replace('__ID__', json.dumps(rid)), 0, lambda result, rid=rid: self._on_poll(rid, result))
            # no response headers after a few seconds: is a verification overlay holding the request?
            now = time.monotonic()
            if info['started'] and not info['meta'] and now - info.get('t0', now) > 4 and now - info.get('probe', 0) > 2:
                info['probe'] = now
                self.page.runJavaScript(VERIFY_OVERLAY_JS, 0, lambda shown, rid=rid: self._on_overlay(rid, shown))

    def _on_overlay(self, rid, shown):
        info = self.requests.get(rid)
        if info is None or info['meta'] or shown is not True: return
        logger.info('qwen_browser verification_overlay_detected')
        # Abort the held request first so it cannot be replayed (and the message sent) after the slider is solved.
        self.page.runJavaScript(ABORT_JS.replace('__ID__', json.dumps(rid)), 0)
        self._fail(rid, 'VERIFICATION')

    def _on_poll(self, rid, result):
        info = self.requests.get(rid)
        if info is None: return
        info['polling'] = False; q = info['queue']
        if isinstance(result, str):
            try: result = json.loads(result)
            except ValueError: result = None
        if not isinstance(result, dict) or result.get('missing'):
            self._fail(rid, 'PAGE_RELOADED'); return
        if result.get('status') is not None and not info['meta']:
            info['meta'] = True; q.put({'kind': 'meta', 'status': int(result['status']), 'ctype': result.get('ctype') or ''})
        if result.get('data'): q.put({'kind': 'data', 'text': result['data']})
        if result.get('done'):
            if result.get('error'): q.put({'kind': 'error', 'error': result['error'], 'message': result.get('message') or ''})
            else: q.put({'kind': 'end'})
            self._finish(rid)

    @Slot(str)
    def _on_abort(self, rid):
        info = self.requests.get(rid)
        if info is None: return
        if info['started']:
            self.page.runJavaScript(ABORT_JS.replace('__ID__', json.dumps(rid)), 0)
        else:
            self._fail(rid, 'ABORTED')

    def _fail(self, rid, code):
        info = self.requests.get(rid)
        if info is None: return
        info['queue'].put({'kind': 'error', 'error': code, 'message': ''}); self._finish(rid)

    def _finish(self, rid):
        with self.lock: self.requests.pop(rid, None)
        if rid in self.pending: self.pending.remove(rid)

    # ----- helpers -----------------------------------------------------------
    def token_present(self, callback):
        """Calls ``callback(bool)`` with whether the page has a login token (the value never leaves the page)."""
        if not (self.loaded and self.on_site()): callback(False); return
        self.page.runJavaScript(TOKEN_PRESENT_JS, 0, lambda r: callback(bool(r)))

    def show_window(self, parent=None, message='', modal=False):
        if self.dialog is None: self.dialog = QwenBrowserDialog(self, parent)
        self.dialog.set_message(message); self.ensure_loaded()
        if modal: return self.dialog.exec()
        self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow()
        return None

    def shutdown(self):
        self.timer.stop()
        for rid in list(self.requests): self._fail(rid, 'ABORTED')
        try:
            import shiboken6
            if self.dialog is not None:
                self.dialog.view.setPage(None); shiboken6.delete(self.dialog); self.dialog = None
            for popup in list(getattr(self.page, 'popups', [])): shiboken6.delete(popup)
            shiboken6.delete(self.page); shiboken6.delete(self.profile)
        except Exception:
            logger.info('qwen_browser shutdown_incomplete')


class QwenBrowserDialog(QDialog):
    continued = Signal()
    DEFAULT_MESSAGE = (tr('در این پنجره خودتان وارد حساب Qwen شوید و اگر تأیید یا کپچا نمایش داده شد، آن را خودتان کامل کنید. '
                       'برنامه کپچا را حل نمی‌کند و کوکی‌ها را جایی منتقل نمی‌کند؛ درخواست‌ها از داخل همین صفحه ارسال می‌شوند. '
                       'پس از ورود، «ادامه» را بزنید.'))

    def __init__(self, browser, parent=None):
        super().__init__(parent); self.browser = browser
        self.setWindowTitle(tr('ورود / تأیید Qwen در مرورگر داخلی')); self.resize(1040, 780); self.setLayoutDirection(layout_direction())
        layout = QVBoxLayout(self)
        self.message = QLabel(); self.message.setWordWrap(True); self.message.setLayoutDirection(layout_direction())
        self.message.setAlignment(label_alignment() | Qt.AlignmentFlag.AlignVCenter); layout.addWidget(self.message)
        self.view = QWebEngineView(self); self.view.setPage(browser.page); layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.continue_button = QPushButton(tr('ادامه')); self.reload_button = QPushButton(tr('بارگذاری دوباره')); self.home_button = QPushButton(tr('صفحهٔ اصلی Qwen')); self.close_button = QPushButton(tr('بستن'))
        for b in (self.continue_button, self.reload_button, self.home_button): row.addWidget(b)
        row.addStretch(); row.addWidget(self.close_button); layout.addLayout(row)
        self.continue_button.clicked.connect(self._continue); self.close_button.clicked.connect(self.reject)
        self.reload_button.clicked.connect(lambda: browser.page.triggerAction(QWebEnginePage.WebAction.Reload))
        self.home_button.clicked.connect(lambda: browser.page.load(QUrl(browser.base + '/')))
        self.set_message('')

    def set_message(self, text):
        self.message.setText((text + '\n\n' if text else '') + self.DEFAULT_MESSAGE)

    def _continue(self):
        self.accept(); self.continued.emit()
