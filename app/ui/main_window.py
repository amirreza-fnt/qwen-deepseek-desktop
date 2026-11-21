from app.i18n import tr, layout_direction, label_alignment, ui_dir, ui_align, resolve as resolve_language
import json, threading, re, time, logging, os, ctypes, html
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QSize, QMimeData
from PySide6.QtGui import QKeyEvent, QTextCursor, QTextOption, QAction, QActionGroup, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
                               QTextBrowser, QTextEdit, QLabel, QMessageBox, QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSpinBox, QComboBox,
                               QFileDialog, QInputDialog, QSplitter, QFrame, QToolButton, QMenu, QTabWidget, QGroupBox, QSizePolicy)
from keyring.backends.Windows import WinVaultKeyring
from app.database.storage import Storage
from app.project import core as project_core
from app.project import tools as project_tools
from app.project import edits as project_edits
from app.ui.project_panel import ProjectPanel
from app.backend.deepseek_adapter import Adapter, BackendError, Cancelled, logger
from app.backend.qwen_adapter import QwenAdapter, QWEN_DEFAULT_MODEL, QWEN_FALLBACK_MODELS
from app.backend.qwen_browser_transport import QwenBrowserAdapter
from app.backend.qwen_protocol import QwenVerificationRequired, token_expired
from app.ui import icons, render, theme
from app.ui.widgets import Composer, ToastHost, StatusIndicator
from app.ui.stream_render import StreamRenderer

SERVICE='DeepSeekDesktop'; USER='web-session'; QWEN_USER='qwen-web-session'
PROVIDERS={'deepseek':'DeepSeek','qwen':'Qwen'}

def qwen_uses_browser(options):
    return (options or {}).get('qwen_transport','browser')!='http'

def token_required(provider, options):
    """DeepSeek and direct-HTTP Qwen need a saved token; the built-in browser uses the page's own login."""
    return not (provider=='qwen' and qwen_uses_browser(options))

def provider_name(provider):
    return PROVIDERS.get(provider or 'deepseek','DeepSeek')

def credential_user(provider='deepseek'):
    # Each provider has its own entry in Windows Credential Manager; the DeepSeek key is unchanged.
    return QWEN_USER if provider=='qwen' else USER

def credential(provider='deepseek'):
    return WinVaultKeyring().get_password(SERVICE, credential_user(provider)) or ''

def clean_token(text):
    text=(text or '').strip().strip('"\'').strip()
    if text.lower().startswith('bearer '): text=text[7:].strip()
    return text.strip('"\'').strip()


SERVER_DETAIL = re.compile(r'\s*\[Qwen server: (.*)\]\s*$', re.S)

def split_server_detail(message):
    """('message without suffix', 'server code: details' or '')."""
    match = SERVER_DETAIL.search(message or '')
    return (message[:match.start()], match.group(1).strip()) if match else (message or '', '')

def persian_error(message, provider='deepseek'):
    """Persian text for a backend error; the real server code/message (if any) is appended verbatim."""
    base, detail = split_server_detail(message)
    text = _persian_base(base, provider)
    return text + (tr('\n\nپاسخ سرور: {detail}', detail=detail) if detail else '')

def _persian_base(message, provider='deepseek'):
    name=provider_name(provider)
    rules = [
        ('saved in Settings has expired',tr('توکن دستی Qwen که در تنظیمات ذخیره شده منقضی شده است (اعتبار توکن‌های وب Qwen فقط حدود ۱۵ دقیقه است). آن را در تنظیمات حذف کنید و از ورود در مرورگر داخلی استفاده کنید.')),
        ('could not refresh it',tr('ورود Qwen در مرورگر داخلی منقضی شده و صفحه نتوانست آن را تازه کند. در پنجرهٔ مرورگر داخلی دوباره وارد شوید و «ادامه» را بزنید.')),
        ('not available in your region',tr('Qwen در منطقهٔ شما در دسترس نیست (سایت chat.qwen.ai این IP را مسدود کرده است). برای استفاده باید VPN سراسری (System-wide) روشن باشد.')),
        ('web firewall',tr('دیوار امنیتی Qwen (Alibaba WAF) تأیید مرورگر یا کپچا خواسته است. در پنجرهٔ «مرورگر داخلی Qwen» تأیید یا کپچا را خودتان کامل کنید، «ادامه» را بزنید و پیام را دوباره بفرستید. برنامه کپچا را حل نمی‌کند.')),
        ('Not logged in to Qwen',tr('در مرورگر داخلی وارد حساب Qwen نشده‌اید. در پنجرهٔ باز‌شده وارد chat.qwen.ai شوید، «ادامه» را بزنید و پیام را دوباره بفرستید.')),
        ('built-in browser could not reach',tr('مرورگر داخلی به Qwen دسترسی پیدا نکرد (اتصال یا VPN را بررسی کنید، یا شاید صفحهٔ تأیید باز شده باشد). پنجرهٔ مرورگر داخلی را ببینید و دوباره تلاش کنید.')),
        ('built-in Qwen page was reloaded',tr('صفحهٔ Qwen در مرورگر داخلی در میانهٔ درخواست دوباره بارگذاری شد. پس از بارگذاری کامل chat.qwen.ai دوباره تلاش کنید.')),
        ('not on chat.qwen.ai',tr('مرورگر داخلی روی سایت chat.qwen.ai نیست. در پنجرهٔ مرورگر داخلی به chat.qwen.ai برگردید و دوباره تلاش کنید.')),
        ('could not load chat.qwen.ai',tr('مرورگر داخلی نتوانست chat.qwen.ai را بارگذاری کند. اتصال و VPN را بررسی کنید.')),
        ('No response from Qwen within',tr('Qwen در مهلت تعیین‌شده پاسخی نداد. شاید مرورگر داخلی منتظر ورود یا تأیید شما باشد؛ پنجرهٔ آن را ببینید و دوباره تلاش کنید.')),
        ('QtWebEngine',tr('مرورگر داخلی (QtWebEngine) در این نسخهٔ برنامه در دسترس نیست. در تنظیمات روش اتصال HTTP را انتخاب کنید یا برنامه را دوباره بسازید.')),
        ('Qwen denied access',tr('Qwen دسترسی را رد کرد (HTTP 403). در مرورگر داخلی وارد شوید یا تأیید را کامل کنید.')),
        ('unexpected web page',tr('Qwen به‌جای داده یک صفحهٔ وب برگرداند؛ احتمالاً ورود یا تأیید لازم است. پنجرهٔ مرورگر داخلی را ببینید.')),
        ('not supported for Qwen',tr('ادامهٔ پاسخ ناقص برای Qwen پشتیبانی نمی‌شود؛ یک پیام پیگیری بفرستید.')),
        ('selected model',tr('Qwen مدل انتخاب‌شده را نپذیرفت. در تنظیمات مدل دیگری انتخاب کنید یا فهرست مدل‌ها را به‌روز کنید.')),
        ('no longer has this remote chat',tr('این گفت‌وگو دیگر روی Qwen وجود ندارد. گفت‌وگو را پاک کنید یا گفت‌وگوی تازه‌ای آغاز کنید.')),
        ('ended without an answer',tr('پاسخ {name} بدون متن پایان یافت. ممکن است درخواست مسدود شده یا رابط خصوصی تغییر کرده باشد.', name=name)),
        ('HTTP 422',tr('زمینهٔ گفت‌وگو از سوی {name} پذیرفته نشد (HTTP 422). شناسهٔ پیام قبلی یا ساختار درخواست را بررسی کنید.', name=name)),
        ('Log in again in the built-in browser',tr('نشست Qwen نامعتبر یا منقضی شده است. در مرورگر داخلی دوباره وارد شوید (یا توکن دستی را در تنظیمات به‌روز کنید)، «ادامه» را بزنید و پیام را دوباره بفرستید.')),
        ('invalid or expired',tr('توکن نشست {name} نامعتبر یا منقضی شده است. آن را در تنظیمات به‌روز کنید.', name=name)),
        ('rate limit',tr('تعداد درخواست‌ها از حد مجاز {name} گذشته است. کمی صبر کنید.', name=name)),
        ('Cloudflare',tr('تأیید Cloudflare لازم است. در وب‌سایت {name} وارد شوید و دوباره تلاش کنید.', name=name)),
        ('Network connection',tr('اتصال شبکه برقرار نشد یا مهلت درخواست پایان یافت.')),
        ('connection was interrupted',tr('اتصال هنگام دریافت پاسخ قطع شد.')),
        ('service is unavailable',tr('سرویس {name} در دسترس نیست. بعداً تلاش کنید.', name=name)),
        ('session ID',tr('پاسخ ساخت نشست، شناسهٔ معتبر ندارد. شاید رابط خصوصی {name} تغییر کرده باشد.', name=name)),
        ('parent message ID',tr('شناسهٔ پیام قبلی نامعتبر است. گفت‌وگوی تازه‌ای آغاز کنید.')),
        ('Enter a Qwen',tr('توکن نشست Qwen در تنظیمات وارد نشده است.')),
        ('Qwen rejected the request',tr('Qwen درخواست را رد کرد. متن پاسخ سرور در زیر آمده است.')),
        ('private API',tr('پاسخ {name} با ساختار شناخته‌شده سازگار نیست. شاید رابط خصوصی تغییر کرده باشد.', name=name)),
    ]
    for needle, translated in rules:
        if needle.lower() in message.lower(): return translated
    return tr('در ارتباط با {name} خطایی رخ داد. جزئیات فنی در گزارش تشخیصی ثبت شده است.', name=name)

class Worker(QThread):
    chunk = Signal(str); session = Signal(str); failed = Signal(str); verify = Signal(str); done = Signal(str, str, bool, bool)
    def __init__(self, token, remote, parent, prompt, options, db_path, cid, user_id=None, assistant_id=None, continue_id=None, initial_text='', provider='deepseek', bridge=None):
        super().__init__(); self.provider=provider or 'deepseek'; self.bridge=bridge; self.token=token; self.remote=remote; self.parent=parent; self.prompt=prompt; self.options=options; self.db_path=db_path; self.cid=cid; self.user_id=user_id; self.assistant_id=assistant_id; self.continue_id=continue_id; self.initial_text=initial_text; self.cancel=threading.Event()
    def run(self):
        content=self.initial_text; emitted_len=len(content); parent=self.continue_id or self.parent; cancelled=False; pending=bool(self.continue_id); acknowledged=bool(self.continue_id); last_flush=last_emit=time.monotonic(); db=None
        try:
            db=Storage(self.db_path); logger.info('worker_start conversation_local_id=%s continuation=%s provider=%s',self.cid,bool(self.continue_id),self.provider)
            if self.provider!='qwen': api=Adapter(self.token,self.options['timeout'],self.cancel)
            elif qwen_uses_browser(self.options): api=QwenBrowserAdapter(self.bridge,self.options['timeout'],self.cancel,self.options.get('qwen_model') or QWEN_DEFAULT_MODEL,self.token)
            else: api=QwenAdapter(self.token,self.options['timeout'],self.cancel,self.options.get('qwen_model') or QWEN_DEFAULT_MODEL)
            if self.provider=='qwen': api.inline_code=bool(self.options.get('qwen_inline_code',True))
            if not self.remote:
                self.remote=api.create_session(); db.execute('UPDATE conversations SET remote_id=? WHERE id=?',(self.remote,self.cid)); self.session.emit(self.remote)
            chunks = api.continue_answer(self.remote,self.continue_id,self.options['auto_continue'],self.initial_text) if self.continue_id else api.stream(self.remote,self.prompt,parent,self.options['thinking'],self.options['search'],self.options['auto_continue'])
            for part in chunks:
                parent=part.get('message_id') or parent
                if part.get('message_id') and not acknowledged:
                    acknowledged=True
                    db.acknowledge_response(self.cid,self.user_id,parent)
                if part['type']=='incomplete': pending=True
                elif part['type']=='complete': pending=False
                else:
                    content+=part['content']
                    if not self.assistant_id: self.assistant_id=db.add(self.cid,'assistant',content,'streaming')
                    now=time.monotonic()
                    if now-last_flush>=0.1:
                        db.update_message(self.assistant_id,content=content); last_flush=now
                    if self.options['streaming'] and now-last_emit>=0.075:
                        self.chunk.emit(content[emitted_len:]); emitted_len=len(content); last_emit=now
        except Cancelled: cancelled=True
        except BackendError as e:
            (self.verify if isinstance(e,QwenVerificationRequired) else self.failed).emit(persian_error(str(e),self.provider)); pending=bool(acknowledged and parent and self.assistant_id)
        except Exception:
            logging.getLogger('deepseek_desktop.backend').error('worker_unexpected_error provider=%s',self.provider)
            self.failed.emit(tr('اتصال {v0} با خطای غیرمنتظره روبه‌رو شد. شاید رابط خصوصی آن تغییر کرده باشد.', v0=provider_name(self.provider))); pending=bool(acknowledged and parent and self.assistant_id)
        try:
            if db:
                if self.assistant_id: db.update_message(self.assistant_id,content,status='interrupted' if pending or cancelled else 'sent')
                if self.user_id and not acknowledged: db.update_message(self.user_id,status='interrupted' if cancelled else 'failed')
                if parent and acknowledged: db.execute('UPDATE conversations SET parent_id=?,pending_id=? WHERE id=?',(str(parent),str(parent) if pending else None,self.cid))
                logger.info('worker_end conversation_local_id=%s acknowledged=%s pending=%s cancelled=%s assistant_chars=%s',self.cid,acknowledged,pending,cancelled,len(content))
                db.db.close()
        except Exception: logging.getLogger('deepseek_desktop.backend').exception('message_persistence_failed')
        if self.options['streaming'] and len(content)>emitted_len: self.chunk.emit(content[emitted_len:])
        self.done.emit(content, str(parent or ''), cancelled, pending and not cancelled)


class ToolRunner(QThread):
    """Runs one project tool off the GUI thread; ``cancel`` kills a running command / download."""
    done = Signal(int, object)
    def __init__(self, index, name, args, root, overlay=None):
        super().__init__(); self.index=index; self.name=name; self.args=args; self.root=root; self.overlay=overlay or {}; self.cancel=threading.Event()
    def run(self):
        result=project_tools.execute(self.name,self.args,self.root,project_tools.Context(self.cancel,overlay=self.overlay))
        self.done.emit(self.index,result)


class Settings(QDialog):
    """Tabbed settings: services (DeepSeek / Qwen), appearance, conversation, about."""
    def __init__(self, parent, values):
        super().__init__(parent); self.setWindowTitle(tr('تنظیمات')); self.resize(680, 620); self.values=values; self.setLayoutDirection(layout_direction())
        layout=QVBoxLayout(self); layout.setContentsMargins(18,18,18,14); layout.setSpacing(12)
        heading=QLabel(tr('تنظیمات')); heading.setObjectName('ChatTitle'); layout.addWidget(heading)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs,1)
        # --- services ---
        services=QWidget(); sv=QVBoxLayout(services); sv.setSpacing(10)
        top=QFormLayout(); top.setLabelAlignment(label_alignment()); sv.addLayout(top)
        self.provider=QComboBox(); self.provider.addItem('DeepSeek (chat.deepseek.com)','deepseek'); self.provider.addItem('Qwen (chat.qwen.ai)','qwen')
        self.provider.setCurrentIndex(1 if values.get('provider')=='qwen' else 0); top.addRow(tr('سرویس گفت‌وگوهای تازه'),self.provider)
        ds=QGroupBox('DeepSeek'); form=QFormLayout(ds); form.setLabelAlignment(label_alignment()); sv.addWidget(ds)
        # DeepSeek token (same Credential Manager entry as before)
        self.status=QLabel(self.token_status('deepseek')); self.status.setObjectName('Muted'); self.status.setWordWrap(True); form.addRow(tr('وضعیت'),self.status)
        self.token=QLineEdit(); self.token.setEchoMode(QLineEdit.EchoMode.Password); self.token.setPlaceholderText(tr('برای نگه‌داشتن توکن فعلی، خالی بگذارید')); form.addRow(tr('توکن نشست وب DeepSeek'),self.token)
        self.remove=QCheckBox(tr('حذف توکن DeepSeek ذخیره‌شده')); form.addRow('',self.remove)
        qw=QGroupBox('Qwen'); form=QFormLayout(qw); form.setLabelAlignment(label_alignment()); sv.addWidget(qw)
        self.qwen_transport=QComboBox(); self.qwen_transport.addItem(tr('مرورگر داخلی (پیشنهادی)'),'browser'); self.qwen_transport.addItem(tr('HTTP مستقیم با توکن (ممکن است با کپچا مسدود شود)'),'http')
        self.qwen_transport.setCurrentIndex(0 if qwen_uses_browser(values) else 1); form.addRow(tr('روش اتصال'),self.qwen_transport)
        self.qwen_browser_button=QPushButton(tr('ورود / تأیید Qwen در مرورگر داخلی')); self.qwen_browser_button.setObjectName('Primary'); self.qwen_browser_button.clicked.connect(self.open_qwen_browser); form.addRow('',self.qwen_browser_button)
        self.qwen_model=QComboBox(); self.qwen_model.setEditable(True); self.qwen_model.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        models=list(dict.fromkeys([values.get('qwen_model') or QWEN_DEFAULT_MODEL]+list(values.get('qwen_models') or [])+QWEN_FALLBACK_MODELS))
        self.qwen_model.addItems(models); self.qwen_model.setCurrentText(values.get('qwen_model') or QWEN_DEFAULT_MODEL); form.addRow(tr('مدل'),self.qwen_model)
        self.qwen_check=QPushButton(tr('بررسی اتصال Qwen و دریافت فهرست مدل‌ها')); self.qwen_check.clicked.connect(self.check_qwen); form.addRow('',self.qwen_check)
        self.qwen_status=QLabel(self.token_status('qwen')); self.qwen_status.setObjectName('Muted'); self.qwen_status.setWordWrap(True); form.addRow(tr('توکن دستی'),self.qwen_status)
        self.qwen_token=QLineEdit(); self.qwen_token.setEchoMode(QLineEdit.EchoMode.Password); self.qwen_token.setPlaceholderText(tr('اختیاری؛ با مرورگر داخلی لازم نیست. خالی = توکن فعلی')); form.addRow(tr('توکن Qwen (اختیاری)'),self.qwen_token)
        self.qwen_show=QCheckBox(tr('نمایش متن توکن تایپ‌شده')); self.qwen_show.toggled.connect(lambda on:(self.qwen_token.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password),self.token.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))); form.addRow('',self.qwen_show)
        self.qwen_remove=QCheckBox(tr('حذف توکن Qwen ذخیره‌شده')); form.addRow('',self.qwen_remove)
        sv.addStretch(); self.tabs.addTab(services,icons.icon('globe','#64748b',16),tr('سرویس‌ها'))
        # --- appearance ---
        look=QWidget(); form=QFormLayout(look); form.setLabelAlignment(label_alignment()); form.setVerticalSpacing(12)
        self.theme=QComboBox(); self.theme.addItem(tr('روشن'),'Light'); self.theme.addItem(tr('تیره'),'Dark'); self.theme.setCurrentIndex(0 if values['theme']=='Light' else 1); form.addRow(tr('پوسته'),self.theme)
        self.language=QComboBox(); self.language.addItem(tr('پیش‌فرض سیستم'),'system'); self.language.addItem('English','en'); self.language.addItem('فارسی','fa')
        self.language.setCurrentIndex(max(0,self.language.findData(values.get('language','system')))); self.language.setToolTip(tr('زبان رابط کاربری؛ پس از راه‌اندازی دوباره اعمال می‌شود.')); form.addRow(tr('زبان / Language'),self.language)
        self.font=QSpinBox(); self.font.setRange(9,24); self.font.setValue(values['font']); self.font.setSuffix(' pt'); form.addRow(tr('اندازهٔ قلم'),self.font)
        note=QLabel(tr('قلم برنامه «وزیرمتن» است (مجوز SIL Open Font License 1.1) و همراه برنامه نصب می‌شود.')); note.setObjectName('Muted'); note.setWordWrap(True); form.addRow('',note)
        self.tabs.addTab(look,icons.icon('sun','#64748b',16),tr('ظاهر'))
        # --- conversation ---
        conv=QWidget(); form=QFormLayout(conv); form.setLabelAlignment(label_alignment()); form.setVerticalSpacing(12)
        self.thinking=QCheckBox(tr('روشن')); self.thinking.setChecked(values['thinking']); form.addRow(tr('تفکر پیش‌فرض'),self.thinking)
        self.search=QCheckBox(tr('روشن')); self.search.setChecked(values['search']); form.addRow(tr('جست‌وجوی وب پیش‌فرض'),self.search)
        self.streaming=QCheckBox(tr('روشن')); self.streaming.setChecked(values['streaming']); form.addRow(tr('نمایش تدریجی پاسخ'),self.streaming)
        self.auto_continue=QCheckBox(tr('روشن')); self.auto_continue.setChecked(values.get('auto_continue',True)); form.addRow(tr('ادامهٔ خودکار پاسخ (فقط DeepSeek)'),self.auto_continue)
        self.qwen_inline_code=QCheckBox(tr('روشن (پیشنهادی)')); self.qwen_inline_code.setChecked(values.get('qwen_inline_code',True)); self.qwen_inline_code.setToolTip(tr('مفسر کد و ابزارهای Qwen خاموش می‌شوند و از مدل خواسته می‌شود همهٔ کد را کامل و در بلوک‌های کد داخل خود پاسخ بنویسد.')); form.addRow(tr('Qwen: کد کامل داخل چت (بدون ابزار)'),self.qwen_inline_code)
        self.timeout=QSpinBox(); self.timeout.setRange(10,300); self.timeout.setSuffix(tr(' ثانیه')); self.timeout.setValue(values['timeout']); form.addRow(tr('مهلت درخواست'),self.timeout)
        self.tabs.addTab(conv,icons.icon('chat','#64748b',16),tr('گفت‌وگو'))
        # --- about ---
        about=QWidget(); av=QVBoxLayout(about)
        label=QLabel(tr('برای Qwen روش «مرورگر داخلی» پیشنهاد می‌شود: یک بار در پنجرهٔ مرورگر داخلی وارد chat.qwen.ai شوید و هر تأیید یا کپچا را خودتان انجام دهید؛ توکن همیشه تازه از همان صفحه خوانده می‌شود و توکن دستی فقط وقتی به کار می‌رود که صفحه توکنی نداشته باشد. توکن‌های وب Qwen فقط حدود ۱۵ دقیقه اعتبار دارند، پس توکن دستی زود منقضی می‌شود.\n\nاین برنامه از رابط‌های غیررسمی وب DeepSeek و Qwen استفاده می‌کند. گذرواژه را وارد نکنید؛ فقط توکن نشست وب را وارد کنید. هر توکن جداگانه در مدیر اعتبارنامهٔ ویندوز ذخیره می‌شود و هر زمان می‌توانید آن را عوض یا حذف کنید. گفت‌وگوهای قبلی با همان سرویسی ادامه می‌یابند که با آن شروع شده‌اند.')); label.setWordWrap(True); av.addWidget(label); av.addStretch()
        self.tabs.addTab(about,icons.icon('info','#64748b',16),tr('درباره'))
        buttons=QDialogButtonBox(); save=buttons.addButton(tr('ذخیره'),QDialogButtonBox.ButtonRole.AcceptRole); save.setObjectName('Primary'); buttons.addButton(tr('انصراف'),QDialogButtonBox.ButtonRole.RejectRole); buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        if parent is not None and hasattr(parent,'options'): self.setStyleSheet(theme.stylesheet(parent.options.get('theme','Light'),parent.options.get('font',12)))

    @staticmethod
    def token_status(provider):
        try: saved=credential(provider)
        except Exception: return tr('مدیر اعتبارنامهٔ ویندوز در دسترس نیست')
        if saved and provider=='qwen' and token_expired(saved):
            return tr('توکن دستی ذخیره‌شده منقضی شده است (اعتبار توکن‌های Qwen حدود ۱۵ دقیقه است)؛ در حالت مرورگر داخلی نادیده گرفته می‌شود. بهتر است آن را حذف کنید.')
        return tr('توکن ذخیره شده است؛ اتصال هنوز بررسی نشده') if saved else tr('توکنی ذخیره نشده است')
    def open_qwen_browser(self):
        window=self.parent()
        if hasattr(window,'show_qwen_browser'): window.show_qwen_browser('',modal=True,parent=self)
    def check_qwen(self):
        token=clean_token(self.qwen_token.text())
        if not token:
            try: token=credential('qwen')
            except Exception: token=''
        browser=self.qwen_transport.currentData()=='browser'
        if not token and not browser: QMessageBox.information(self,'Qwen',tr('ابتدا توکن Qwen را وارد کنید.')); return
        bridge=None
        if browser:
            bridge=self.parent().get_qwen_browser() if hasattr(self.parent(),'get_qwen_browser') else None
            if bridge is None: QMessageBox.warning(self,'Qwen',persian_error('The built-in browser (QtWebEngine) is not available','qwen')); return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor); self.qwen_check.setEnabled(False)
        try:
            api=QwenBrowserAdapter(bridge,min(self.timeout.value(),30),model=self.qwen_model.currentText(),token=token) if browser else QwenAdapter(token,min(self.timeout.value(),30))
            api.check_token(); models=api.list_models()
            current=self.qwen_model.currentText(); self.qwen_model.clear(); self.qwen_model.addItems(models)
            self.qwen_model.setCurrentText(current if current in models else models[0]); self.values['qwen_models']=models
            self.qwen_status.setText(tr('اتصال Qwen پذیرفته شد؛ ')+str(len(models))+tr(' مدل دریافت شد'))
        except BackendError as e:
            self.qwen_status.setText(tr('بررسی ناموفق بود')); QApplication.restoreOverrideCursor(); QApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor); QMessageBox.warning(self,'Qwen',persian_error(str(e),'qwen'))
            if browser and isinstance(e,QwenVerificationRequired): self.open_qwen_browser()
        except Exception:
            logger.error('qwen_check_unexpected_error'); QMessageBox.warning(self,'Qwen',tr('بررسی توکن Qwen با خطای غیرمنتظره روبه‌رو شد.'))
        finally:
            QApplication.restoreOverrideCursor(); self.qwen_check.setEnabled(True)
    def save(self):
        try:
            vault=WinVaultKeyring()
            for provider,field,remove in (('deepseek',self.token,self.remove),('qwen',self.qwen_token,self.qwen_remove)):
                if remove.isChecked():
                    if credential(provider): vault.delete_password(SERVICE,credential_user(provider))
                elif clean_token(field.text()): vault.set_password(SERVICE,credential_user(provider),clean_token(field.text()))
            self.values.update(provider=self.provider.currentData(),qwen_transport=self.qwen_transport.currentData(),qwen_model=self.qwen_model.currentText().strip() or QWEN_DEFAULT_MODEL,theme=self.theme.currentData(),language=self.language.currentData(),thinking=self.thinking.isChecked(),search=self.search.isChecked(),streaming=self.streaming.isChecked(),auto_continue=self.auto_continue.isChecked(),qwen_inline_code=self.qwen_inline_code.isChecked(),font=self.font.value(),timeout=self.timeout.value()); self.accept()
        except Exception: QMessageBox.critical(self,tr('ذخیرهٔ توکن'),tr('ذخیرهٔ توکن در مدیر اعتبارنامهٔ ویندوز ممکن نشد.'))



class ChatView(QTextBrowser):
    """Chat document view; copying a selection drops the visual padding at the start of code lines."""
    def createMimeDataFromSelection(self):
        data=super().createMimeDataFromSelection()
        if data is not None and data.hasText():
            out=QMimeData(); out.setText(render.strip_code_pad(data.text()).replace('\u2063','').replace('\u2064','')); return out
        return data

class Window(QMainWindow, ToastHost):
    def __init__(self, storage=None):
        super().__init__(); self.store=storage or Storage(); self.store.recover_interrupted(); self.options=self.store.settings(); self.cid=None; self.worker=None; self.preview=''; self.page_before=None; self.first_loaded_id=None; self.code_blocks=[]; self.worker_provider='deepseek'; self.qwen_browser=None; self.qwen_browser_error=False; self.stream_cursor=None; self.stream_renderer=None; self.stream_pending=''
        self.resize(1180,780); self.setMinimumSize(760,520); self.setLayoutDirection(layout_direction())
        if not self.options.get('light_blue_migration'):
            self.options['theme']='Light'; self.options['light_blue_migration']=True; self.store.save_settings(self.options)
        theme.load_fonts(); self.palette_values=theme.palette(self.options['theme'])
        root=QWidget(); self.setCentralWidget(root); outer=QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        splitter=QSplitter(); splitter.setHandleWidth(1); splitter.setChildrenCollapsible(False); outer.addWidget(splitter)
        # ---- sidebar ----
        side=QFrame(); side.setObjectName('Sidebar'); side.setMinimumWidth(230); side.setMaximumWidth(380)
        sl=QVBoxLayout(side); sl.setContentsMargins(14,16,14,12); sl.setSpacing(10)
        brand=QHBoxLayout(); self.logo=QLabel(); brand.addWidget(self.logo); names=QVBoxLayout(); names.setSpacing(0)
        title=QLabel(tr('دستیار گفت‌وگو')); title.setObjectName('Brand'); sub=QLabel(tr('DeepSeek · Qwen — غیررسمی')); sub.setObjectName('BrandSub')
        names.addWidget(title); names.addWidget(sub); brand.addLayout(names,1); sl.addLayout(brand)
        self.new=QPushButton(tr('گفت‌وگوی جدید')); self.new.setObjectName('Primary'); self.new.setCursor(Qt.CursorShape.PointingHandCursor); self.new.setToolTip(tr('شروع گفت‌وگوی جدید')); sl.addWidget(self.new)
        self.searchbox=QLineEdit(); self.searchbox.setObjectName('SearchBox'); self.searchbox.setPlaceholderText(tr('جست‌وجوی گفت‌وگوها')); self.searchbox.setClearButtonEnabled(True)
        self.search_action=QAction(self.searchbox); self.searchbox.addAction(self.search_action,QLineEdit.ActionPosition.LeadingPosition); sl.addWidget(self.searchbox)
        caption=QLabel(tr('گفت‌وگوها')); caption.setObjectName('Muted'); sl.addWidget(caption)
        self.list=QListWidget(); self.list.setObjectName('ChatList'); self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel); self.list.setTextElideMode(Qt.TextElideMode.ElideLeft); sl.addWidget(self.list,1)
        foot=QHBoxLayout(); foot.setSpacing(4)
        self.settings=QToolButton(); self.settings.setText(tr('تنظیمات')); self.settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.settings.setObjectName('Ghost')
        self.diagnostics=QToolButton(); self.diagnostics.setToolTip(tr('گزارش تشخیصی')); self.theme_toggle=QToolButton(); self.theme_toggle.setToolTip(tr('تغییر پوسته (روشن / تیره)'))
        foot.addWidget(self.settings); foot.addStretch(); foot.addWidget(self.diagnostics); foot.addWidget(self.theme_toggle); sl.addLayout(foot)
        splitter.addWidget(side)
        # ---- main column ----
        main=QFrame(); main.setObjectName('Main'); ml=QVBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        header=QFrame(); header.setObjectName('Header'); hl=QHBoxLayout(header); hl.setContentsMargins(20,10,14,10); hl.setSpacing(6)
        titles=QVBoxLayout(); titles.setSpacing(0); self.title=QLabel(tr('گفت‌وگوی جدید')); self.title.setObjectName('ChatTitle'); self.status=StatusIndicator()
        titles.addWidget(self.title); titles.addWidget(self.status); hl.addLayout(titles,1)
        self.provider_pill=QToolButton(); self.provider_pill.setObjectName('Pill'); self.provider_pill.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup); self.provider_pill.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.provider_pill.setLayoutDirection(Qt.LayoutDirection.LeftToRight); self.provider_pill.setToolTip(tr('سرویس و مدل گفت‌وگوهای تازه')); self.provider_menu=QMenu(self.provider_pill); self.provider_pill.setMenu(self.provider_menu)
        self.provider_menu.aboutToShow.connect(self.build_provider_menu); hl.addWidget(self.provider_pill)
        self.provider_label=QLabel(); self.provider_label.setObjectName('Muted'); self.provider_label.setVisible(False)
        self.project_button=QToolButton(); self.project_button.setText(tr('پروژه')); self.project_button.setCheckable(True); self.project_button.setObjectName('Chip')
        self.project_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.project_button.setToolTip(tr('حالت پروژه: پوشهٔ پروژه، فایل‌ها و تغییرات پیشنهادی')); hl.addWidget(self.project_button)
        self.rename=QToolButton(); self.export=QToolButton(); self.clear=QToolButton(); self.delete=QToolButton()
        for b,tip in ((self.rename,tr('تغییر نام گفت‌وگو')),(self.export,tr('خروجی گفت‌وگو (Markdown / JSON)')),(self.clear,tr('پاک‌کردن پیام‌ها و شروع نشست تازه')),(self.delete,tr('حذف گفت‌وگو'))):
            b.setToolTip(tip); b.setIconSize(QSize(18,18)); hl.addWidget(b)
        ml.addWidget(header)
        paging=QHBoxLayout(); paging.setContentsMargins(20,6,20,0); self.older=QPushButton(tr('پیام‌های قدیمی‌تر')); self.latest=QPushButton(tr('آخرین پیام‌ها'))
        for b in (self.older,self.latest): b.setObjectName('Ghost'); paging.addWidget(b)
        paging.addStretch(); ml.addLayout(paging)
        self.chat=ChatView(); self.chat.setObjectName('Chat'); self.chat.setOpenExternalLinks(False); self.chat.setOpenLinks(False); self.chat.anchorClicked.connect(self.copy_code_link)
        self.chat.setLayoutDirection(layout_direction()); self.chat.setFrameShape(QFrame.Shape.NoFrame)
        chat_wrap=QHBoxLayout(); chat_wrap.setContentsMargins(18,0,18,0); chat_wrap.addWidget(self.chat); ml.addLayout(chat_wrap,1)
        # ---- composer ----
        dock=QVBoxLayout(); dock.setContentsMargins(22,8,22,14); dock.setSpacing(6)
        box=QFrame(); box.setObjectName('ComposerBox'); bl=QVBoxLayout(box); bl.setContentsMargins(12,8,10,8); bl.setSpacing(4)
        self.composer=Composer(box); self.composer.setPlaceholderText(tr('پیام خود را بنویسید…')); bl.addWidget(self.composer)
        tools=QHBoxLayout(); tools.setSpacing(6)
        self.thinking=QToolButton(); self.thinking.setText(tr('تفکر')); self.thinking.setCheckable(True); self.search=QToolButton(); self.search.setText(tr('جست‌وجوی وب')); self.search.setCheckable(True)
        for b,tip in ((self.thinking,tr('حالت تفکر (استدلال طولانی‌تر)')),(self.search,tr('جست‌وجو در وب'))):
            b.setObjectName('Chip'); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); b.setToolTip(tip); b.setIconSize(QSize(15,15)); tools.addWidget(b)
        tools.addStretch()
        self.copy=QToolButton(); self.retry=QToolButton(); self.continue_button=QToolButton(); self.continue_button.setEnabled(False)
        for b,tip in ((self.copy,tr('کپی متن انتخاب‌شده یا آخرین پیام')),(self.retry,tr('تلاش دوباره برای آخرین پیام ناموفق')),(self.continue_button,tr('ادامهٔ پاسخ ناقص (برای Qwen یک پیام «ادامه بده» در همان گفت‌وگو فرستاده می‌شود)'))):
            b.setToolTip(tip); b.setIconSize(QSize(18,18)); tools.addWidget(b)
        self.stop=QToolButton(); self.stop.setObjectName('StopButton'); self.stop.setFixedSize(36,36); self.stop.setToolTip(tr('توقف')); self.stop.setEnabled(False); self.stop.setVisible(False)
        self.send=QToolButton(); self.send.setObjectName('SendButton'); self.send.setFixedSize(36,36); self.send.setToolTip(tr('ارسال (Enter)')); self.send.setCursor(Qt.CursorShape.PointingHandCursor)
        tools.addWidget(self.stop); tools.addWidget(self.send); bl.addLayout(tools)
        dock.addWidget(box)
        hint=QLabel(tr('پاسخ‌ها از رابط‌های غیررسمی وب دریافت می‌شوند و ممکن است نادرست باشند.')); hint.setObjectName('Muted'); hint.setAlignment(Qt.AlignmentFlag.AlignCenter); dock.addWidget(hint)
        ml.addLayout(dock); splitter.addWidget(main); splitter.setStretchFactor(1,1)
        self.project_panel=ProjectPanel(theme.palette(self.options['theme'])); self.project_panel.setMinimumWidth(300); self.project_panel.setVisible(False)
        splitter.addWidget(self.project_panel); splitter.setSizes([280,900,0]); self.splitter=splitter
        self.project_cid=object(); self.project_changes={}; self.project_parse_at=0.0
        self.agent=None; self.agent_steps={}; self.tool_runner=None; self.tool_expanded=set()
        self.project_panel.tools.setChecked(bool(self.options.get('project_tools',True))); self.project_panel.tools.toggled.connect(self.set_project_tools)
        self.project_button.toggled.connect(self.toggle_project_panel); self.project_panel.choose_folder.connect(self.choose_project_folder)
        self.project_panel.mode_toggled.connect(self.set_project_mode); self.project_panel.attached_changed.connect(self.set_project_files)
        self.project_panel.ask_fix.connect(self.ask_project_fix); self.project_panel.changes_applied.connect(self.on_project_applied)
        self.init_toasts(150)
        self.stream_timer=QTimer(self); self.stream_timer.setSingleShot(True); self.stream_timer.setInterval(90); self.stream_timer.timeout.connect(self._flush_stream)
        self.new.clicked.connect(self.new_chat); self.searchbox.textChanged.connect(self.refresh_list); self.list.currentRowChanged.connect(self.select_chat); self.rename.clicked.connect(self.rename_chat); self.delete.clicked.connect(self.delete_chat); self.settings.clicked.connect(self.open_settings); self.diagnostics.clicked.connect(self.open_diagnostics); self.send.clicked.connect(self.send_message); self.composer.send.connect(self.send_message); self.stop.clicked.connect(self.stop_request); self.clear.clicked.connect(self.clear_chat); self.retry.clicked.connect(self.retry_message); self.continue_button.clicked.connect(self.continue_response); self.copy.clicked.connect(self.copy_message); self.export.clicked.connect(self.export_chat); self.older.clicked.connect(self.load_older); self.latest.clicked.connect(self.load_latest)
        self.theme_toggle.clicked.connect(self.toggle_theme)
        self.thinking.setChecked(self.options['thinking']); self.search.setChecked(self.options['search']); self.apply_theme(); self.update_provider_label(); self.refresh_list(); self.render()
        self.set_status('idle')
        if self.options.get('provider')=='qwen' and qwen_uses_browser(self.options): QTimer.singleShot(300,self.get_qwen_browser)
        self.last_tick=time.monotonic(); self.tick_count=0; self.monitor=QTimer(self); self.monitor.timeout.connect(self.monitor_ui); self.monitor.start(1000)
    # ---- look -------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event); self._layout_toasts()
    def apply_theme(self):
        p=self.palette_values=theme.palette(self.options['theme'])
        self.setStyleSheet(theme.stylesheet(self.options['theme'],self.options['font']))
        font=QFont(theme.FONT_FAMILY); font.setPointSize(self.options['font']); font.setHintingPreference(QFont.HintingPreference.PreferNoHinting); self.chat.document().setDefaultFont(font); self.chat.document().setDocumentMargin(14)
        self.chat.document().setDefaultStyleSheet(render.document_css(p))
        ic=p['icon']
        self.logo.setPixmap(icons.pixmap('spark',p['accent'],30)); self.new.setIcon(icons.icon('plus',p['accent_text'],18)); self.search_action.setIcon(icons.icon('search',p['muted'],16))
        self.settings.setIcon(icons.icon('settings',ic,18)); self.diagnostics.setIcon(icons.icon('activity',ic,18)); self.theme_toggle.setIcon(icons.icon('sun' if self.options['theme']=='Dark' else 'moon',ic,18))
        for b,name in ((self.rename,'edit'),(self.export,'export'),(self.clear,'eraser'),(self.delete,'trash'),(self.copy,'copy'),(self.retry,'retry'),(self.continue_button,'continue')): b.setIcon(icons.icon(name,ic,18))
        self.thinking.setIcon(icons.icon('bulb',p['muted'],15)); self.search.setIcon(icons.icon('globe',p['muted'],15))
        self.send.setIcon(icons.icon('send',p['accent_text'],20)); self.send.setIconSize(QSize(20,20)); self.stop.setIcon(icons.icon('stop',p['bg'],18)); self.stop.setIconSize(QSize(18,18))
        self.provider_pill.setIcon(icons.icon('chevron',p['muted'],14)); self.status.set_palette(p)
        self.project_button.setIcon(icons.icon('folder',p['muted'],15)); self.project_panel.p=p; self.project_panel.undo.setIcon(icons.icon('undo',ic,16))
    def toggle_theme(self):
        self.options['theme']='Dark' if self.options['theme']=='Light' else 'Light'; self.store.save_settings(self.options); self.apply_theme(); self.render()
    def set_status(self, state, text=None):
        if text is None: text={'idle':tr('آماده'),'busy':tr('در حال دریافت پاسخ'),'error':tr('خطا')}.get(state,'')
        self.status.set_state(state,text)
    def notify(self, text, kind='info', action=None):
        return self.toast(text,kind,action)
    # ---- provider pill ----------------------------------------------------------
    def update_provider_label(self, conv=None):
        selected=self.options.get('provider','deepseek')
        provider=conv['provider'] if conv is not None and conv['remote_id'] and conv['provider'] else selected
        text=tr('سرویس: ')+provider_name(provider)+(f" · {self.options.get('qwen_model') or QWEN_DEFAULT_MODEL} · "+(tr('مرورگر داخلی') if qwen_uses_browser(self.options) else 'HTTP') if provider=='qwen' else '')
        if provider!=selected: text+=tr(' (این گفت‌وگو با ')+provider_name(provider)+tr(' شروع شده است)')
        self.provider_label.setText(text); self.setWindowTitle(tr('گفت‌وگوی {v0} · غیررسمی', v0=provider_name(selected)))
        pill=provider_name(provider)+(f" · {self.options.get('qwen_model') or QWEN_DEFAULT_MODEL}" if provider=='qwen' else '')
        self.provider_pill.setText(pill+'  '); self.provider_pill.setToolTip(text)
    def build_provider_menu(self):
        menu=self.provider_menu; menu.clear(); group=QActionGroup(menu)
        locked=self.chat_locked_provider()
        if locked: header=menu.addAction(tr('این گفت‌وگو با ')+provider_name(locked)+tr(' ادامه می‌یابد')); header.setEnabled(False); menu.addSeparator()
        for key in ('deepseek','qwen'):
            action=menu.addAction(provider_name(key)+(' (chat.deepseek.com)' if key=='deepseek' else ' (chat.qwen.ai)')); action.setCheckable(True); action.setChecked(self.options.get('provider','deepseek')==key); group.addAction(action)
            action.triggered.connect(lambda _=False,k=key: self.set_provider(k))
        menu.addSeparator(); sub=menu.addMenu(tr('مدل Qwen')); mgroup=QActionGroup(sub)
        current=self.options.get('qwen_model') or QWEN_DEFAULT_MODEL
        for model in dict.fromkeys([current]+list(self.options.get('qwen_models') or [])+QWEN_FALLBACK_MODELS):
            a=sub.addAction(model); a.setCheckable(True); a.setChecked(model==current); mgroup.addAction(a); a.triggered.connect(lambda _=False,m=model: self.set_qwen_model(m))
        menu.addSeparator(); menu.addAction(icons.icon('browser',self.palette_values['icon'],16),tr('ورود / تأیید Qwen در مرورگر داخلی'),lambda: self.show_qwen_browser(''))
        menu.addAction(icons.icon('settings',self.palette_values['icon'],16),tr('تنظیمات بیشتر…'),self.open_settings)
    def chat_locked_provider(self):
        row=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone() if self.cid else None
        return (row['provider'] or 'deepseek') if row is not None and row['remote_id'] else None
    def set_provider(self, provider):
        if self.options.get('provider')==provider: return
        self.options['provider']=provider; self.store.save_settings(self.options); self.render()
        locked=self.chat_locked_provider()
        if locked and locked!=provider: self.notify(tr('گفت‌وگوهای تازه با {v0} آغاز می‌شوند؛ این گفت‌وگو با {v1} ادامه می‌یابد.', v0=provider_name(provider), v1=provider_name(locked)))
        if provider=='qwen' and qwen_uses_browser(self.options): QTimer.singleShot(100,self.get_qwen_browser)
    def set_qwen_model(self, model):
        self.options['qwen_model']=model; self.store.save_settings(self.options); self.update_provider_label(self.current_conv())
    def current_conv(self):
        return self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone() if self.cid else None
    # ---- conversations ----------------------------------------------------------
    def refresh_list(self):
        self.list.blockSignals(True); self.list.clear(); rows=self.store.conversations(self.searchbox.text()); selected=-1
        for i,r in enumerate(rows):
            item=QListWidgetItem(r['title']); item.setData(Qt.ItemDataRole.UserRole,r['id']); item.setToolTip(r['title']+' · '+provider_name(r['provider']))
            item.setIcon(icons.icon('chat',self.palette_values['accent'] if r['provider']=='qwen' else self.palette_values['muted'],16))
            self.list.addItem(item)
            if r['id']==self.cid: selected=i
        self.list.setCurrentRow(selected); self.list.blockSignals(False)
    def select_chat(self, row):
        item=self.list.item(row)
        if item: self.cid=item.data(Qt.ItemDataRole.UserRole); self.preview=''; self.page_before=None; self.render()
    def new_chat(self):
        if self.worker: return
        self.cid=self.store.create(provider=self.options.get('provider','deepseek')); self.page_before=None; self.refresh_list(); self.render(); self.composer.setFocus()
    def load_older(self):
        if self.first_loaded_id: self.page_before=self.first_loaded_id; self.render()
    def load_latest(self):
        self.page_before=None; self.render()
    # ---- project mode ---------------------------------------------------------------------------------------
    def toggle_project_panel(self, on):
        self.project_panel.setVisible(on)
        if on:
            sizes=self.splitter.sizes()
            if sizes[2]<300: self.splitter.setSizes([sizes[0],max(400,sizes[1]-380),380])
    def sync_project(self, force=False):
        if self.project_cid==self.cid and not force: return
        self.project_cid=self.cid; root,mode,files=self.store.project(self.cid)
        self.project_panel.set_project(root,mode,files); self.project_panel.set_changes(self.project_changes.get(self.cid,[])); self.project_panel.set_progress('')
        if root and not self.project_button.isChecked(): self.project_button.setChecked(True)
    def choose_project_folder(self):
        if self.worker: return
        start=self.store.project(self.cid)[0] if self.cid else ''
        folder=QFileDialog.getExistingDirectory(self,tr('انتخاب پوشه پروژه'),start or str(Path.home()))
        if folder: self.bind_project_folder(folder)
    def bind_project_folder(self, folder):
        if not self.cid: self.new_chat()
        self.store.set_project(self.cid,root=str(Path(folder)),mode=True,files=[]); self.project_changes.pop(self.cid,None); self.sync_project(True)
        self.project_button.setChecked(True); self.notify(tr('حالت پروژه برای این گفت‌وگو روشن شد. فایل‌های لازم را تیک بزنید یا با @ نام ببرید.'),'success')
    def set_project_mode(self, on):
        if self.cid: self.store.set_project(self.cid,mode=on)
    def set_project_files(self, files):
        if self.cid: self.store.set_project(self.cid,files=files)
    def project_active(self):
        root,mode,files=self.store.project(self.cid)
        return (root,files) if root and mode and os.path.isdir(root) else (None,[])
    def project_prompt(self, text):
        root,files=self.project_active()
        if not root: return text
        prompt,report=project_core.build_prompt(root,text,files,tools=self.project_tools_on())
        problems=[rel for rel,_,note in report if note in ('too_large','unreadable')]
        if problems: self.notify(tr('این فایل‌ها پیوست نشدند (بزرگ یا ناخوانا): ')+tr('، ').join(problems[:5]),'error')
        if any(note=='truncated' for _,_,note in report): self.notify(tr('بعضی فایل‌ها برای جا شدن در زمینه کوتاه شدند.'),'info')
        if len(prompt)>project_core.CONTEXT_BUDGET_CHARS: self.notify(tr('حجم زمینهٔ پروژه زیاد است ({v0:,} نویسه)؛ ممکن است مدل آن را کامل نخواند.', v0=len(prompt)),'error')
        logger.info('project_prompt files=%s chars=%s',len(report),len(prompt))
        return prompt
    def update_project_progress(self, text, final=False):
        root,_=self.project_active()
        if not root: return
        now=time.monotonic()
        if not final and now-self.project_parse_at<0.4: return
        self.project_parse_at=now; ops=project_core.parse_ops(text,final=False)
        if ops:
            last=ops[-1]; done=sum(1 for o in ops if o.complete)
            self.project_panel.set_progress(tr('در حال دریافت تغییرات: {done} فایل کامل', done=done) + (tr(' · در حال نوشتن {path}', path=last.path) if not last.complete else ''))
    def review_project_reply(self, text):
        root,_=self.project_active()
        if not root or not text: return
        ops=project_core.parse_ops(text,final=True); self.turn_edit_results={}
        calls=project_tools.parse_calls(text,final=True) if self.project_tools_on() else []
        edit_calls=[(i,c) for i,c in enumerate(calls) if project_tools.is_edit_tool(c.name)]
        if not ops and not edit_calls: self.project_panel.set_progress(''); return
        # inside an agent loop the new proposal builds on the still-pending one (one batch for the user to review)
        base=[c for c in self.project_changes.get(self.cid,[]) if c.state=='pending' and not c.error] if self.agent_steps.get(self.cid,0)>0 else []
        changes,results=project_edits.plan_turn(root,ops,[(c.pos,c.name,c.args,c.error) for _,c in edit_calls],base)
        for (i,_),res in zip(edit_calls,results): self.turn_edit_results[i]=res
        logger.info('project_plan ops=%s edit_tools=%s changes=%s',len(ops),len(edit_calls),len(changes))
        self.project_changes[self.cid]=changes
        if not changes:
            self.project_panel.set_changes([]); self.project_panel.set_progress(tr('ابزارهای ویرایش تغییری پیشنهاد نکردند.')); return
        self.project_panel.set_changes(changes); self.project_panel.set_progress(tr('تغییرات را بررسی کنید؛ تا «اعمال» را نزنید چیزی نوشته نمی‌شود.'))
        self.project_button.setChecked(True)
        errors=sum(1 for c in changes if c.state=='error')
        self.notify(tr('{v0} تغییر پیشنهادی آمادهٔ بررسی است', v0=len(changes))+(tr(' ({errors} مورد خطا دارد)', errors=errors) if errors else ''),'error' if errors else 'success')
    def ask_project_fix(self, change):
        self.composer.setPlainText(tr('تغییر پیشنهادی برای فایل {path} اعمال نشد: {error}\nلطفاً با توجه به محتوای فعلی همین فایل (پیوست شده) یک بلوک edit درست بفرست که SEARCH آن دقیقاً و فقط یک‌بار در فایل باشد، یا کل فایل را با بلوک file بفرست.', path=change.path, error=change.error))
        if change.old is not None: self.project_panel.set_attached([change.path])
        self.composer.setFocus(); self.notify(tr('متن درخواست اصلاح در کادر پیام آماده است؛ بررسی کنید و بفرستید.'))
    def on_project_applied(self, paths):
        self.notify(tr('{v0} فایل نوشته شد (نسخهٔ قبلی در تاریخچه ذخیره شد).', v0=len(paths)),'success')
    # ---- project agent: tool calls ---------------------------------------------------------------------------
    def project_tools_on(self):
        return self.project_panel.tools.isChecked()
    def set_project_tools(self, on):
        self.options['project_tools']=bool(on)
        try: self.store.save_settings({'project_tools':bool(on)})
        except Exception: logger.exception('settings_failed')
    def tool_row_html(self, r, p):
        try: record=json.loads(r['content'])
        except ValueError: record={'calls':[]}
        out=render.tool_cards_html(record,r['id'],p,self.tool_expanded)
        if r['status'] in ('failed','interrupted'):
            out+=tr('<p dir="rtl" style="color:{v0}; font-size:small;">ارسال نتایج ابزار به مدل انجام نشد؛ «تلاش دوباره» را بزنید.</p>', v0=p["danger"])
        return out
    def agent_after_reply(self, text):
        """After a final reply in project mode: run the tool blocks it contains (one round), then send the results."""
        root,_=self.project_active()
        if not root or not text or not self.project_tools_on(): return
        calls=project_tools.parse_calls(text,final=True)
        if not calls: return
        cid=self.cid; step=self.agent_steps.get(cid,0)+1; limit=int(self.options.get('agent_max_steps',project_tools.MAX_STEPS))
        if step>limit:
            self.notify(tr('سقف {limit} مرحلهٔ ابزار برای این درخواست رسید و عامل متوقف شد. برای ادامه، پیام تازه‌ای بفرستید.', limit=limit),'error'); return
        self.agent_steps[cid]=step
        record={'step':step,'calls':[dict(name=c.name,args=c.args,summary=c.summary(),state='error' if c.error else 'pending',
                                          output=c.error,status='invalid' if c.error else '') for c in calls]}
        edit_results=getattr(self,'turn_edit_results',{}) or {}
        for i,c in enumerate(record['calls']):
            if project_tools.is_edit_tool(c['name']):   # planned by review_project_reply: proposal only, nothing written yet
                ok,msg=edit_results.get(i,(False,c['output'] or tr('اجرا نشد')))
                c['state']='done' if ok else 'error'; c['status']=tr('در پنل بازبینی') if ok else tr('خطا')
                c['output']=(msg+'\n(proposed: shown to the user as a diff; written only after the user clicks Apply)') if ok else msg
        mid=self.store.add(cid,'tool',json.dumps(record,ensure_ascii=False),'pending')
        self.agent={'cid':cid,'mid':mid,'record':record,'root':root}
        logger.info('agent_round step=%s tools=%s',step,','.join(c.name for c in calls))
        self.agent_busy_ui(True); self.render(); self.advance_agent()
    def save_agent(self):
        a=self.agent
        if a: self.store.update_message(a['mid'],content=json.dumps(a['record'],ensure_ascii=False))
    def render_agent(self):
        if self.agent and self.agent['cid']==self.cid: self.render()
    def agent_busy_ui(self, on):
        busy=bool(on or self.worker)
        self.stop.setVisible(busy); self.stop.setEnabled(busy)
        if not self.worker: self.send.setVisible(True); self.send.setEnabled(True)
    def advance_agent(self):
        a=self.agent
        if not a or self.tool_runner: return
        for i,c in enumerate(a['record']['calls']):
            if c['state']=='awaiting': return
            if c['state']!='pending': continue
            call=project_tools.ToolCall(c['name'],c.get('args') or {})
            if not c.get('approved') and project_tools.needs_approval(call,self.project_panel.allow_ro.isChecked()):
                c['state']='awaiting'; self.save_agent(); self.render_agent(); self.set_status('busy',tr('منتظر تأیید شما'))
                self.notify(tr('مدل می‌خواهد «')+render.TOOL_LABEL.get(c['name'],c['name'])+tr('» را اجرا کند. کارت آن را در گفت‌وگو بررسی کنید و «اجرا» یا «رد» را بزنید.'))
                return
            c['state']='running'; self.save_agent(); self.render_agent(); self.set_status('busy',tr('در حال اجرای ')+render.TOOL_LABEL.get(c['name'],c['name']))
            overlay={ch.path:(None if ch.kind=='delete' else ch.new) for ch in self.project_changes.get(a['cid'],[])
                     if ch.state=='pending' and not ch.error and ch.raw is None and ch.kind!='mkdir'}
            self.tool_runner=ToolRunner(i,c['name'],c.get('args') or {},a['root'],overlay)
            self.tool_runner.done.connect(self.on_tool_done); self.tool_runner.start(); return
        self.agent_send_results()
    def on_tool_done(self, index, result):
        runner=self.tool_runner; self.tool_runner=None
        if runner is not None: runner.wait(3000); runner.deleteLater()
        a=self.agent
        if not a: return
        c=a['record']['calls'][index]
        c['state']='done' if result.ok else 'error'; c['output']=result.output; c['status']=result.status
        logger.info('agent_tool name=%s ok=%s status=%s output_chars=%s',c['name'],result.ok,result.status,len(result.output))
        if a.get('stopping'): self.finish_agent(tr('عامل متوقف شد')); return
        self.save_agent(); self.render_agent(); self.advance_agent()
    def tool_link(self, kind, mid, index):
        if kind=='toggle':
            self.tool_expanded^={f'{mid}:{index}'}; self.render(keep_scroll=True); return
        a=self.agent
        if not a or a['mid']!=mid or index>=len(a['record']['calls']):
            self.notify(tr('این درخواست ابزار دیگر فعال نیست.')); return
        c=a['record']['calls'][index]
        if kind=='approve' and c['state']=='awaiting':
            c['state']='pending'; c['approved']=True; logger.info('agent_tool_approved name=%s',c['name']); self.advance_agent()
        elif kind=='reject' and c['state']=='awaiting':
            c['state']='rejected'; c['output']=''; logger.info('agent_tool_rejected name=%s',c['name']); self.save_agent(); self.render_agent(); self.advance_agent()
        elif kind=='kill' and c['state']=='running' and self.tool_runner is not None:
            self.tool_runner.cancel.set(); self.notify(tr('اجرای ابزار متوقف می‌شود…'))
    def stop_agent(self, quiet=False):
        a=self.agent
        if not a: return
        for c in a['record']['calls']:
            if c['state'] in ('pending','awaiting'): c['state']='skipped'; c['output']=''
        if self.tool_runner is not None:
            a['stopping']=True; self.tool_runner.cancel.set(); self.save_agent(); return
        self.finish_agent('' if quiet else tr('عامل متوقف شد'))
    def finish_agent(self, message=''):
        a=self.agent
        if not a: return
        self.save_agent(); self.store.update_message(a['mid'],status='sent'); self.agent=None
        self.agent_steps[a['cid']]=0; self.agent_busy_ui(False)
        if not self.worker: self.set_status('idle',message or None)
        if a['cid']==self.cid: self.render()
    def agent_send_results(self):
        a=self.agent
        if not a or any(c['state'] in ('pending','awaiting','running') for c in a['record']['calls']): return
        calls=a['record']['calls']
        if all(project_tools.is_edit_tool(c['name']) and c['state']=='done' for c in calls):
            # only edit tools and all planned: nothing to report back, the user reviews the proposal (saves a model turn)
            self.finish_agent(tr('تغییرات پیشنهادی آمادهٔ بررسی است')); return
        if self.worker or a['cid']!=self.cid: a['send_when_free']=True; return
        a['send_when_free']=False
        provider=self.chat_provider()
        try: token=credential(provider)
        except Exception: token=''
        if not token and token_required(provider,self.options):
            self.notify(tr('توکن {v0} ذخیره نشده است؛ نتایج ابزار فرستاده نشد.', v0=provider_name(provider)),'error'); self.store.update_message(a['mid'],status='failed'); self.agent=None; self.agent_busy_ui(False); self.render(); return
        self.save_agent(); prompt=project_tools.format_results(a['record']['calls']); mid=a['mid']; self.agent=None
        logger.info('agent_send_results tools=%s chars=%s',len(a['record']['calls']),len(prompt))
        row=self.bind_provider(); self.start(token,row,prompt,user_id=mid,raw=True)
    def render(self, keep_scroll=False):
        scroll_value=self.chat.verticalScrollBar().value(); render_start=time.monotonic(); p=self.palette_values; self.stream_cursor=None; self.stream_renderer=None; self.stream_pending=''
        self.sync_project()
        for w in (self.rename,self.export,self.clear,self.delete): w.setEnabled(bool(self.cid) and not self.worker)
        if not self.cid:
            self.code_blocks=[]; self.title.setText(tr('گفت‌وگوی جدید')); self.continue_button.setEnabled(False); self.older.setVisible(False); self.latest.setVisible(False)
            self.update_provider_label(); self.chat.setHtml(render.empty_state(p,provider_name(self.options.get('provider','deepseek')))); return
        rows=self.store.messages_page(self.cid,self.page_before); conv=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone()
        if not conv: return
        self.first_loaded_id=rows[0]['id'] if rows else None
        has_older=bool(self.first_loaded_id and self.store.db.execute('SELECT 1 FROM messages WHERE conversation_id=? AND id<? LIMIT 1',(self.cid,self.first_loaded_id)).fetchone())
        self.older.setEnabled(has_older); self.older.setVisible(has_older); self.latest.setEnabled(self.page_before is not None); self.latest.setVisible(self.page_before is not None)
        self.title.setText(conv['title']); self.update_provider_label(conv); name=provider_name(conv['provider']); self.continue_button.setEnabled(bool(conv['pending_id']) and not self.worker); parts=[]; self.code_blocks=[]
        for r in rows:
            if r['role']=='tool':
                parts.append(self.tool_row_html(r,p)); continue
            body=render.message_html(r['content'],self.code_blocks,p) if r['role']!='user' else render.message_html(r['content'],self.code_blocks,dict(p,inline_code='#6a62f0',text='#ffffff',muted='#e0e7ff',link='#ffffff'))
            parts.append(render.bubble(r['role'],name,body,p,r['status'],render.direction(r['content'])))
        streaming=self.worker is not None and self.worker_cid==self.cid and self.page_before is None
        if streaming: parts.append(render.streaming_html(name,'',p))
        if not parts: self.chat.setHtml(render.empty_state(p,name)); return
        self.chat.setHtml('<div>'+''.join(parts)+'<p style="margin-top:12px;">&nbsp;</p></div>')
        if streaming:
            found=self.chat.document().find(render.STREAM_MARK)
            if not found.isNull():
                found.setPosition(found.selectionStart()); self.stream_cursor=found
                self.stream_renderer=StreamRenderer(self.chat.document(),found,p)
                if self.preview: self.stream_renderer.feed(self.preview)
        doc=self.chat.document(); doc.documentLayout().blockBoundingRect(doc.lastBlock())  # finish Qt's lazy layout so the bottom is the real bottom
        self.chat.verticalScrollBar().setValue(min(scroll_value,self.chat.verticalScrollBar().maximum()) if keep_scroll else self.chat.verticalScrollBar().maximum())
        a=self.agent
        if a and a.get('send_when_free') and not self.worker and a['cid']==self.cid: QTimer.singleShot(0,self.agent_send_results)
        elapsed=time.monotonic()-render_start
        if elapsed>0.1: logger.info('chat_render_seconds=%.3f visible_messages=%s',elapsed,len(rows))
    def mark_code(self, content):
        """Compatibility helper: collect code snippets (fenced and inline) of ``content`` into ``code_blocks``."""
        render.message_html(content,self.code_blocks,self.palette_values); return content
    def copy_code_link(self, url):
        tool=re.fullmatch(r'tool-(toggle|approve|reject|kill):(\d+):(\d+)',url.toString())
        if tool: self.tool_link(tool.group(1),int(tool.group(2)),int(tool.group(3))); return
        stream=re.fullmatch(r'copy-stream:(\d+)',url.toString())
        if stream and self.stream_renderer is not None:
            code=self.stream_renderer.code_for_link(int(stream.group(1)))
            if code is not None:
                QApplication.clipboard().setText(code.rstrip('\n'))
                if self.isVisible(): self.notify(tr('کد (تا این لحظه) کپی شد'),'success')
            return
        match=re.fullmatch(r'copy-code:(\d+)',url.toString())
        if match and int(match.group(1)) < len(self.code_blocks):
            QApplication.clipboard().setText(self.code_blocks[int(match.group(1))])
            if self.isVisible(): self.notify(tr('کد کپی شد'),'success')
    def offer_restart(self):
        """The UI language is applied at startup; offer to restart the app now."""
        new=resolve_language(self.options.get('language','system'))
        title='Language' if new=='en' else 'زبان'
        text=('The new language will be applied after restarting the app. Restart now?' if new=='en' else 'زبان جدید پس از راه‌اندازی دوبارهٔ برنامه اعمال می‌شود. همین حالا دوباره راه‌اندازی شود؟')
        if QMessageBox.question(self,title,text)!=QMessageBox.StandardButton.Yes: return
        import sys
        from PySide6.QtCore import QProcess
        args=sys.argv[1:] if getattr(sys,'frozen',False) else [os.path.abspath(sys.argv[0])]+sys.argv[1:]
        if QProcess.startDetached(sys.executable,args): self.close(); QApplication.quit()
    def open_settings(self):
        try:
            dialog=Settings(self,self.options.copy())
            old_language=self.options.get('language','system')
            if dialog.exec():
                self.options=dialog.values; self.store.save_settings(self.options); self.apply_theme(); self.refresh_list(); self.render()
                if self.options.get('language','system')!=old_language: self.offer_restart()
        except Exception: logger.exception('settings_failed'); QMessageBox.critical(self,tr('تنظیمات'),tr('مدیر اعتبارنامهٔ ویندوز در دسترس نیست.'))
    # ---- sending ------------------------------------------------------------------
    def send_message(self):
        text=self.composer.toPlainText().strip()
        if not text or self.worker: return
        if self.tool_runner: self.notify(tr('یک ابزار در حال اجراست؛ صبر کنید یا «توقف» را بزنید.')); return
        if self.agent: self.stop_agent(quiet=True)
        provider=self.chat_provider()
        try: token=credential(provider)
        except Exception:
            if token_required(provider,self.options): QMessageBox.critical(self,tr('توکن'),tr('مدیر اعتبارنامهٔ ویندوز در دسترس نیست.')); return
            token=''
        if not token and token_required(provider,self.options): self.notify(tr('توکن {v0} ذخیره نشده است. آن را در تنظیمات وارد کنید.', v0=provider_name(provider)),'error'); self.open_settings(); return
        if not self.cid: self.new_chat()
        row=self.bind_provider()
        if not self.store.latest_message(self.cid): self.store.execute('UPDATE conversations SET title=? WHERE id=?',(text[:55],self.cid)); self.refresh_list()
        try:
            user_id=self.store.add(self.cid,'user',text,'pending')
            self.store.execute('UPDATE conversations SET thinking=?,search=? WHERE id=?',(self.thinking.isChecked(),self.search.isChecked(),self.cid))
        except Exception:
            self.notify(tr('پیام در پایگاه داده ذخیره نشد؛ متن همچنان در کادر ارسال باقی مانده است.'),'error')
            return
        self.agent_steps[self.cid]=0
        self.composer.clear(); self.start(token,row,text,user_id=user_id)
    def start(self,token,row,text,continue_id=None,initial_text='',user_id=None,assistant_id=None,raw=False):
        provider=row['provider'] or 'deepseek'; self.worker_provider=provider
        bridge=None
        if provider=='qwen' and qwen_uses_browser(self.options):
            bridge=self.get_qwen_browser()
            if bridge is None:
                self.notify(persian_error('The built-in browser (QtWebEngine) is not available','qwen'),'error')
                if user_id: self.store.update_message(user_id,status='failed')
                self.render(); return
        if not continue_id and not raw: text=self.project_prompt(text)
        opts=dict(self.options,thinking=self.thinking.isChecked(),search=self.search.isChecked()); self.preview=''; self.preview_baseline=initial_text; self.preview_started=False; self.page_before=None
        self.worker=Worker(token,row['remote_id'],row['parent_id'],text,opts,self.store.path,self.cid,user_id,assistant_id,continue_id,initial_text,provider,bridge); self.worker_cid=self.cid
        if continue_id and assistant_id: self.preview=''
        self.render()
        self.worker.session.connect(lambda sid: None)
        self.worker.chunk.connect(self.update_preview); self.worker.failed.connect(lambda msg,p=provider: self.on_failed(msg,p)); self.worker.verify.connect(self.on_qwen_verify); self.worker.done.connect(self.finished); self.worker.finished.connect(self.thread_finished)
        for w in [self.new,self.list,self.delete,self.rename,self.clear,self.settings,self.send,self.retry,self.continue_button]: w.setEnabled(False)
        self.send.setVisible(False); self.stop.setVisible(True); self.stop.setEnabled(True); self.set_status('busy',tr('{v0} در حال پاسخ', v0=provider_name(provider))); self.worker.start()
    def on_failed(self, message, provider):
        self.set_status('error',tr('ارسال ناموفق بود'))
        self.notify(message,'error',(tr('تلاش دوباره'),self.retry_message))
    def update_preview(self,delta):
        """Streamed text: buffered and rendered incrementally (Markdown + code blocks) at most every 90 ms."""
        if not delta: return
        self.preview+=delta; self.stream_pending+=delta
        if not self.stream_timer.isActive(): self.stream_timer.start()
    def _flush_stream(self):
        if not self.stream_pending: return
        if self.stream_renderer is None:
            self.stream_pending=''
            if self.worker is not None and self.cid==getattr(self,'worker_cid',None) and self.page_before is None: self.render()
            return
        bar=self.chat.verticalScrollBar(); at_bottom=bar.value()>=bar.maximum()-60
        started=time.monotonic(); pending,self.stream_pending=self.stream_pending,''
        self.stream_renderer.feed(pending); self.update_project_progress(self.preview)
        if at_bottom: bar.setValue(bar.maximum())
        elapsed=time.monotonic()-started
        if elapsed>0.25: logger.info('stream_render_seconds=%.3f chars=%s',elapsed,len(self.preview))
    def finished(self,text,parent,cancelled,pending):
        self.stream_timer.stop(); self.preview=''; self.stream_cursor=None; self.stream_renderer=None; self.stream_pending=''
        same=getattr(self,'worker_cid',None)==self.cid
        self.worker_cid=None; self.render(); self.done_rendered=self.cid  # the reply is final: no streaming bubble any more
        if same: self.review_project_reply(text)
        if same and not cancelled and not pending: self.agent_after_reply(text)
        if cancelled: self.set_status('idle',tr('متوقف شد'))
        elif self.status.state!='error': self.set_status('idle')
    def thread_finished(self):
        self.worker.deleteLater(); self.worker=None
        for w in [self.new,self.list,self.delete,self.rename,self.clear,self.settings,self.send,self.retry]: w.setEnabled(True)
        self.stop.setEnabled(False); self.stop.setVisible(False); self.send.setVisible(True)
        if self.cid and getattr(self,'done_rendered',None)==self.cid and self.page_before is None:
            # The final reply was already rendered by finished(): only refresh the actions (a second full
            # render of a very long reply took seconds on Windows).
            conv=self.current_conv()
            for w in (self.rename,self.export,self.clear,self.delete): w.setEnabled(True)
            self.continue_button.setEnabled(bool(conv and conv['pending_id']))
        else:
            self.render()
        self.done_rendered=None
        if self.agent:
            self.agent_busy_ui(True)
            if self.agent.get('send_when_free'): QTimer.singleShot(0,self.agent_send_results)
    def get_qwen_browser(self):
        """Lazily create the built-in Qwen browser (GUI thread). Returns None if QtWebEngine is unavailable."""
        if self.qwen_browser is None and not self.qwen_browser_error:
            try:
                from app.ui.qwen_browser import QwenBrowser
                self.qwen_browser=QwenBrowser(parent=self); self.qwen_browser.ensure_loaded()
            except Exception:
                self.qwen_browser_error=True; logger.exception('qwen_browser_unavailable')
        return self.qwen_browser
    def show_qwen_browser(self,message='',modal=False,parent=None):
        browser=self.get_qwen_browser()
        if browser is None: self.notify(persian_error('The built-in browser (QtWebEngine) is not available','qwen'),'error'); return
        if browser.dialog is None:
            from app.ui.qwen_browser import QwenBrowserDialog
            browser.dialog=QwenBrowserDialog(browser,self); browser.dialog.continued.connect(self.qwen_browser_continued)
        browser.show_window(parent or self,message,modal)
    def on_qwen_verify(self,message):
        self.pending_verify_retry=True; self.set_status('error',tr('ورود یا تأیید Qwen لازم است'))
        self.show_qwen_browser(message+tr('\n\nپس از ورود یا تأیید، «ادامه» را بزنید؛ سپس می‌توانید پیام را با یک کلیک دوباره بفرستید (ارسال خودکار انجام نمی‌شود).'))
    def qwen_browser_continued(self):
        if not getattr(self,'pending_verify_retry',False) or not self.cid: return
        if self.worker: self.notify(tr('درخواست قبلی هنوز در حال پایان است؛ چند لحظه بعد «تلاش دوباره» را بزنید.')); return
        self.pending_verify_retry=False
        last=self.store.latest_message(self.cid)
        if last and last['role']=='user' and last['status'] in ('failed','interrupted'):
            if QMessageBox.question(self,tr('ارسال دوباره'),tr('آخرین پیام شما دوباره به Qwen فرستاده شود؟'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.retry_message()
    def chat_provider(self):
        """Provider for the selected chat: a chat with a remote session keeps its provider; an unsent chat follows Settings."""
        row=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone() if self.cid else None
        if row is not None and row['remote_id']: return row['provider'] or 'deepseek'
        return self.options.get('provider','deepseek')
    def bind_provider(self):
        row=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone()
        if row is not None and not row['remote_id'] and row['provider']!=self.options.get('provider','deepseek'):
            self.store.execute('UPDATE conversations SET provider=?,parent_id=NULL,pending_id=NULL WHERE id=?',(self.options.get('provider','deepseek'),self.cid))
            row=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone()
        return row
    def monitor_ui(self):
        now=time.monotonic(); gap=now-self.last_tick; self.last_tick=now; self.tick_count+=1
        if gap>1.5: logger.warning('ui_stall_seconds=%.2f',gap)
        if self.tick_count%10==0:
            class MemoryCounters(ctypes.Structure):
                _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong),('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
            try:
                counters=MemoryCounters(); counters.cb=ctypes.sizeof(counters)
                if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(counters),counters.cb): logger.info('working_set_bytes=%s peak_bytes=%s',counters.WorkingSetSize,counters.PeakWorkingSetSize)
            except (AttributeError,OSError): pass
    def open_diagnostics(self):
        dialog=QDialog(self); dialog.setWindowTitle(tr('گزارش تشخیصی')); dialog.resize(760,500)
        layout=QVBoxLayout(dialog); view=QTextEdit(); view.setReadOnly(True); layout.addWidget(view)
        path=Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'DeepSeekDesktop'/'diagnostics.log'
        try: view.setPlainText(path.read_text(encoding='utf-8')[-100000:])
        except OSError: view.setPlainText(tr('هنوز گزارشی ثبت نشده است.'))
        export=QPushButton(tr('خروجی گزارش')); layout.addWidget(export)
        def save():
            target,_=QFileDialog.getSaveFileName(dialog,tr('ذخیرهٔ گزارش'),'diagnostics.log','Log (*.log)')
            if target: Path(target).write_text(view.toPlainText(),encoding='utf-8')
        export.clicked.connect(save); dialog.exec()
    def continue_response(self):
        if not self.cid or self.worker: return
        row=self.store.db.execute('SELECT * FROM conversations WHERE id=?',(self.cid,)).fetchone()
        if not row or not row['pending_id'] or not row['remote_id']: return
        try: token=credential(row['provider'] or 'deepseek')
        except Exception: token=''
        if not token and token_required(row['provider'] or 'deepseek',self.options): self.open_settings(); return
        last=self.store.latest_message(self.cid,'assistant')
        self.start(token,row,'',row['pending_id'],last['content'] if last else '',assistant_id=last['id'] if last else None)
    def stop_request(self):
        if self.worker: self.worker.cancel.set(); self.stop.setEnabled(False)
        if self.agent: self.stop_agent()
    def retry_message(self):
        if not self.cid or self.worker: return
        last=self.store.latest_message(self.cid)
        if not last: return
        if last['role']=='assistant' or last['status'] not in ('failed','interrupted'): self.notify(tr('«تلاش دوباره» فقط برای پیام ناموفق یا قطع‌شدهٔ شما فعال است.')); return
        provider=self.chat_provider()
        try: token=credential(provider)
        except Exception: token=''
        if not token and token_required(provider,self.options): self.open_settings(); return
        row=self.bind_provider(); self.store.update_message(last['id'],status='pending')
        if last['role']=='tool':   # resend the tool results of this round
            try: calls=json.loads(last['content']).get('calls',[])
            except (ValueError,AttributeError): calls=[]
            for c in calls:
                if c.get('state') in ('pending','awaiting','running'): c['state']='skipped'; c['output']=''
            self.start(token,row,project_tools.format_results(calls),user_id=last['id'],raw=True)
        else: self.start(token,row,last['content'],user_id=last['id'])
    def rename_chat(self):
        if not self.cid: return
        title,ok=QInputDialog.getText(self,tr('تغییر نام گفت‌وگو'),tr('عنوان:'))
        if ok and title.strip(): self.store.execute('UPDATE conversations SET title=? WHERE id=?',(title.strip(),self.cid)); self.refresh_list(); self.render()
    def delete_chat(self):
        if self.cid and QMessageBox.question(self,tr('حذف گفت‌وگو'),tr('این گفت‌وگوی محلی حذف شود؟'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.store.execute('DELETE FROM conversations WHERE id=?',(self.cid,)); self.cid=None; self.refresh_list(); self.render()
    def clear_chat(self):
        if self.cid and QMessageBox.question(self,tr('پاک‌کردن گفت‌وگو'),tr('پیام‌ها پاک شوند و نشست تازه‌ای آغاز شود؟'),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.store.execute('DELETE FROM messages WHERE conversation_id=?',(self.cid,)); self.store.execute('UPDATE conversations SET remote_id=NULL,parent_id=NULL,pending_id=NULL WHERE id=?',(self.cid,)); self.render()
    def copy_message(self):
        text=self.chat.textCursor().selectedText().replace('\u2029','\n')
        if not text and self.cid:
            rows=self.store.messages(self.cid); text=rows[-1]['content'] if rows else ''
        QApplication.clipboard().setText(text)
        if text: self.notify(tr('در کلیپ‌بورد کپی شد'),'success')
    def export_chat(self):
        if not self.cid: return
        path,kind=QFileDialog.getSaveFileName(self,tr('خروجی گفت‌وگو'),'conversation.md','Markdown (*.md);;JSON (*.json)')
        if not path: return
        rows=[dict(r) for r in self.store.messages(self.cid)]
        try:
            data=json.dumps(rows,ensure_ascii=False,indent=2) if kind.startswith('JSON') else '\n\n'.join('## '+r['role'].title()+'\n\n'+r['content'] for r in rows)
            Path(path).write_text(data,encoding='utf-8')
        except OSError: self.notify(tr('نوشتن فایل انتخاب‌شده ممکن نشد.'),'error')
        else: self.notify(tr('گفت‌وگو ذخیره شد'),'success')
    def closeEvent(self,event):
        if self.tool_runner: self.tool_runner.cancel.set(); self.tool_runner.wait(5000)
        if self.worker: self.worker.cancel.set(); event.ignore()
        else:
            if self.qwen_browser is not None: self.qwen_browser.shutdown(); self.qwen_browser=None
            self.store.db.close(); event.accept()

