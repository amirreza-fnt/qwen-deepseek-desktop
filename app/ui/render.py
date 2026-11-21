"""Chat transcript rendering for the QTextBrowser: chat bubbles, Markdown and highlighted code blocks.

Qt's rich-text engine supports a subset of HTML/CSS (tables, background colours, padding, fonts),
so bubbles are tables. Code is highlighted with Pygments (inline styles) and each code block or inline
code span gets a ``copy-code:N`` link that the window copies to the clipboard.
"""
from app.i18n import tr, layout_direction, label_alignment, ui_dir, ui_align
import html, re
try:
    import markdown as _markdown
except ImportError:  # pragma: no cover - fallback keeps the app usable without the package
    _markdown = None
try:
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, guess_lexer, TextLexer
    from pygments.util import ClassNotFound
except ImportError:  # pragma: no cover
    highlight = None

FENCED = re.compile(r'(?m)^(?P<fence>`{3,})(?P<lang>[^\n`]*)\n(?P<code>.*?)^(?P=fence)[ \t]*$', re.S)
INLINE = re.compile(r'(?<!`)`([^`\n]+)`(?!`)')
MAX_HIGHLIGHT_CHARS = 400000
FENCE_OPEN = re.compile(r'(?m)^(?P<fence>`{3,})(?P<lang>[^\n`]*)\n')
FENCE_CLOSE = re.compile(r'(?m)^```[ \t]*(?:\n|$)')

def fence_close(fence):
    """Closing-line regex for an opening fence of ``fence`` (``` or ```` …)."""
    return re.compile(r'(?m)^' + re.escape(fence) + r'[ \t]*(?:\n|$)')
MONO = "font-family:Consolas,Vazirmatn,'Cascadia Mono','Courier New',monospace;"  # Vazirmatn right after Consolas: Persian text inside code keeps normal letter spacing
STREAM_MARK = '\u2063'  # invisible separator: marks where streamed text is inserted

_RTL = re.compile('[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]')
_LTR = re.compile('[A-Za-z]')

def direction(text):
    """'rtl' if the first strong character is Persian/Arabic/Hebrew, else 'ltr'."""
    for ch in text:
        if _RTL.match(ch): return 'rtl'
        if _LTR.match(ch): return 'ltr'
    return ui_dir()

_FORMATTER = None

def lexer_for(lang, code=''):
    if highlight is None: return None
    m = re.match(r'\s*(?:file|edit|delete)\s*:\s*(\S+)', lang or '')
    if m and highlight is not None:   # project-mode blocks: pick the lexer from the file name
        try: return get_lexer_for_filename(m.group(1), stripnl=False)
        except ClassNotFound: return TextLexer(stripnl=False)
    lang = (lang or '').strip().split()[0].lower() if (lang or '').strip() else ''
    # stripnl=False: keep leading/trailing blank lines (line counts must match the source exactly)
    try: return get_lexer_by_name(lang, stripnl=False) if lang else TextLexer(stripnl=False)
    except ClassNotFound:
        try: return guess_lexer(code, stripnl=False) if code and len(code) < 4000 else TextLexer(stripnl=False)
        except ClassNotFound: return TextLexer(stripnl=False)

def highlight_lines(code, lexer):
    """Highlighted HTML for ``code`` (Pygments inline styles), newlines as <br/>, indentation preserved."""
    global _FORMATTER
    if highlight is None or lexer is None or len(code) > MAX_HIGHLIGHT_CHARS:
        out = html.escape(code)
    else:
        if _FORMATTER is None: _FORMATTER = HtmlFormatter(noclasses=True, nowrap=True, style='monokai')  # dark in both themes
        out = highlight(code, lexer, _FORMATTER)
        if not code.endswith('\n') and out.endswith('\n'): out = out[:-1]
    return out.replace('  ', '&nbsp; ').replace('\n', '<br/>')

def _highlight(code, lang, p):
    return highlight_lines(code, lexer_for(lang, code))

CODE_PAD = '\u2002\u2002'  # visual left padding of code lines (block backgrounds ignore padding/text-indent); stripped on copy

def strip_code_pad(text):
    return re.sub('(?m)^' + CODE_PAD, '', text)

def code_line_style(p):
    return (f'background-color:{p["code_bg"]}; margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; '
            f'white-space:pre-wrap; {MONO} color:{p["code_text"]};')  # wrap: a line wider than the RTL chat would push the start of every line out of view

def code_lines_html(body_html, p):
    """One LTR paragraph per code line. No tables: Qt re-lays out a whole table on every change, while plain
    paragraphs are laid out one by one, so a streaming block with thousands of lines stays fast."""
    style = code_line_style(p)
    return ''.join(f'<p dir="ltr" align="left" style="{style}">{CODE_PAD}{line}</p>' for line in body_html.split('<br/>'))

def code_block_html(lang, index, p, body='', scheme='copy-code'):
    label = html.escape((lang or '').strip() or 'code')
    pad = f'background-color:{p["code_bg"]}; margin-left:0px; margin-right:0px; font-size:4pt;'
    return (tr('<p dir="ltr" align="left" style="background-color:{v0}; margin-top:10px; margin-bottom:0px; margin-left:0px; margin-right:0px; color:#94a3b8; font-size:small; white-space:pre;"><span style="{MONO}">{CODE_PAD}{label}</span>&nbsp;&nbsp;&nbsp;<a href="{scheme}:{index}" style="color:#a5b4fc; text-decoration:none;">کپی کد</a></p><p dir="ltr" style="{pad} margin-top:0px; margin-bottom:0px;">&nbsp;</p>', v0=p["code_head"], MONO=MONO, CODE_PAD=CODE_PAD, label=label, scheme=scheme, index=index, pad=pad)
            + code_lines_html(body, p) +
            f'<p dir="ltr" style="{pad} margin-top:0px; margin-bottom:10px;">&nbsp;</p>')

def _code_block(code, lang, index, p):
    return code_block_html(lang, index, p, highlight_lines(code.rstrip('\n'), lexer_for(lang, code)))

_BLOCK_TAG = re.compile(r'<(p|li|h[1-6]|blockquote|td|th)>(.*?)</\1>', re.S)
_TAGS = re.compile(r'<[^>]+>')

def add_dir(out):
    """Per-paragraph bidi: each block gets dir=rtl/ltr from its first strong character."""
    def repl(m):
        text = html.unescape(_TAGS.sub('', m.group(2)))
        d = direction(text)
        align = ' align="left"' if d == 'ltr' else ''
        return f'<{m.group(1)} dir="{d}"{align}>{m.group(2)}</{m.group(1)}>'
    return _BLOCK_TAG.sub(repl, out)

def _prose(text, blocks, p, scheme='copy-code'):
    if not text.strip(): return ''
    tokens = {}
    def inline(match):
        index = len(blocks); blocks.append(match.group(1)); key = f'QINLINECODE{index}Q'
        tokens[key] = (tr('<a href="{scheme}:{index}" title="برای کپی کلیک کنید" style="text-decoration:none; color:{v0};"><span style="font-family:Consolas,Vazirmatn,\'Cascadia Mono\',monospace; background-color:{v1};">&nbsp;{v2}&nbsp;</span></a>', scheme=scheme, index=index, v0=p["text"], v1=p["inline_code"], v2=html.escape(match.group(1))))
        return key
    text = INLINE.sub(inline, text).replace('<', '&lt;')
    if _markdown is not None:
        out = _markdown.markdown(text, extensions=['tables', 'sane_lists'], output_format='html')
    else:
        out = '<p>' + text.replace('\n\n', '</p><p>').replace('\n', '<br/>') + '</p>'
    for key, value in tokens.items(): out = out.replace(key, value)
    out = add_dir(out)
    out = out.replace('<table>', f'<table border="1" cellspacing="0" cellpadding="6" style="border-color:{p["border"]}; border-style:solid;">')
    return out

def message_html(content, blocks, p):
    """Markdown with fenced code blocks -> rich-text HTML. Appends every code snippet to ``blocks``."""
    parts = []; last = 0
    for match in FENCED.finditer(content):
        parts.append(_prose(content[last:match.start()], blocks, p))
        index = len(blocks); blocks.append(match.group('code').rstrip('\n'))
        parts.append(_code_block(match.group('code').rstrip('\n'), match.group('lang'), index, p))
        last = match.end()
    rest = content[last:]
    opened = FENCE_OPEN.search(rest)
    if opened:  # unterminated fence (cut-off or still streaming): the rest is code
        parts.append(_prose(rest[:opened.start()], blocks, p))
        code = rest[opened.end():]; index = len(blocks); blocks.append(code.rstrip('\n'))
        parts.append(_code_block(code, opened.group('lang'), index, p))
    else:
        parts.append(_prose(rest, blocks, p))
    return ''.join(parts)

STATUS_LABELS = {'pending': tr('در انتظار ارسال'), 'streaming': tr('در حال دریافت'), 'failed': tr('ناموفق'), 'interrupted': tr('قطع‌شده')}

def bubble(role, name, body_html, p, status='', dir_='rtl'):
    label = STATUS_LABELS.get(status, '')
    status_html = ''
    if label:
        color = p['danger'] if status in ('failed', 'interrupted') else p['muted']
        status_html = f'&nbsp;·&nbsp;<span style="color:{color};">{label}</span>'
    if role == 'user':
        return (tr('<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:16px;"><tr><td width="22%"></td><td><p align="right" style="color:{v0}; font-size:small; margin-bottom:4px;">شما{status_html}</p><table width="100%" cellspacing="0" cellpadding="12" bgcolor="{v1}"><tr><td dir="{dir_}" style="color:{v2};">{body_html}</td></tr></table></td></tr></table>', v0=p["muted"], status_html=status_html, v1=p["user_bubble"], dir_=dir_, v2=p["user_text"], body_html=body_html))
    # Assistant replies are laid out directly in the document flow (no table bubble), like modern chat apps;
    # this also keeps incremental streaming fast (tables are re-laid out completely on every change).
    return (f'<p style="color:{p["muted"]}; font-size:small; margin-top:20px; margin-bottom:6px;"><span style="color:{p["accent"]};">✦</span>&nbsp;{html.escape(name)}{status_html}</p>'
            f'{body_html}')

def streaming_html(name, text, p):
    body = html.escape(text).replace('\n', '<br/>') + STREAM_MARK
    return bubble('assistant', name, f'<p dir="{direction(text) if text else ui_dir()}">{body}</p>', p, 'streaming')

def empty_state(p, provider):
    return (tr('<table width="100%" height="100%" cellpadding="0"><tr><td align="center" style="padding-top:90px;"><p align="center" style="font-size:28pt; color:{v0};">✦</p><p align="center" style="font-size:x-large; font-weight:700;">چه کمکی از دستم برمی‌آید؟</p><p align="center" style="color:{v1};">گفت‌وگو با {v2} · پیام خود را در کادر پایین بنویسید</p><p align="center" style="color:{v1}; font-size:small;">Enter برای ارسال · Shift+Enter برای خط جدید</p></td></tr></table>', v0=p["accent"], v1=p["muted"], v2=html.escape(provider)))

def document_css(p):
    return (f'body {{ color:{p["text"]}; }} a {{ color:{p["link"]}; }} '
            f'h1, h2, h3, h4 {{ margin-top:10px; margin-bottom:6px; }} p {{ margin-top:4px; margin-bottom:4px; }} '
            f'li {{ margin-bottom:3px; }} blockquote {{ color:{p["muted"]}; }}')

# ----- project-mode tool activity (agent) ---------------------------------------------------------------------------
TOOL_STATE = {'pending': ('⏳', tr('در صف'), 'muted'), 'awaiting': ('⚠', tr('منتظر تأیید شما'), 'warning'),
              'running': ('⟳', tr('در حال اجرا…'), 'accent'), 'done': ('✓', tr('انجام شد'), 'success'),
              'error': ('✕', tr('خطا'), 'danger'), 'rejected': ('⦸', tr('رد شد'), 'muted'), 'skipped': ('⦸', tr('اجرا نشد'), 'muted')}
TOOL_LABEL = {'list_dir': tr('ساختار پوشه'), 'find_files': tr('یافتن فایل'), 'search': tr('جست‌وجو در فایل‌ها'), 'read_file': tr('خواندن فایل'),
              'image_info': tr('بررسی تصویر'), 'http_request': tr('درخواست HTTP'), 'download_file': tr('دانلود فایل'), 'run_command': tr('اجرای فرمان'),
              'count_lines': tr('شمارش خطوط'), 'move_lines': tr('انتقال خطوط'), 'copy_lines': tr('کپی خطوط'), 'delete_lines': tr('حذف خطوط'),
              'replace_lines': tr('جایگزینی خطوط'), 'insert_text': tr('درج متن'), 'insert_file_content': tr('درج محتوای فایل'),
              'replace_text': tr('جست‌وجو و جایگزینی'), 'move_path': tr('انتقال مسیر'), 'rename_path': tr('تغییر نام'), 'copy_path': tr('کپی مسیر'),
              'make_dir': tr('ساخت پوشه'), 'apply_patch': tr('اعمال patch')}
MAX_TOOL_LINES = 400

def _mono_lines(text, p, limit=MAX_TOOL_LINES):
    lines = text.split('\n')
    if len(lines) > limit: lines = lines[:limit] + [f'… ({len(lines) - limit} more lines)']
    body = '<br/>'.join(html.escape(l).replace('  ', '&nbsp; ') for l in lines)
    return code_lines_html(body, p)

def tool_cards_html(record, mid, p, expanded=()):
    """Collapsible cards for one tool round (a 'tool' message). Links: tool-toggle/approve/reject/kill:<mid>:<i>."""
    calls = record.get('calls') or []
    step = record.get('step') or 1
    out = [tr('<p dir="rtl" style="color:{v0}; font-size:small; margin-top:18px; margin-bottom:6px;"><span style="color:{v1};">⚙</span>&nbsp;ابزارهای پروژه · مرحلهٔ {step}</p>', v0=p["muted"], v1=p["accent"], step=step)]
    link = f'color:{p["link"]}; text-decoration:none; font-weight:600;'
    for i, c in enumerate(calls):
        icon, label, color_key = TOOL_STATE.get(c.get('state'), ('•', c.get('state', ''), 'muted'))
        name = c.get('name', ''); title = TOOL_LABEL.get(name, name)
        status = f' · {html.escape(c["status"])}' if c.get('status') and c.get('state') in ('done', 'error') else ''
        actions = []
        state = c.get('state'); key = f'{mid}:{i}'
        if state == 'awaiting':
            actions.append(tr('<a href="tool-approve:{key}" style="{link} color:{v0};">✔ اجرا</a>', key=key, link=link, v0=p["success"]))
            actions.append(tr('<a href="tool-reject:{key}" style="{link} color:{v0};">✖ رد</a>', key=key, link=link, v0=p["danger"]))
        elif state == 'running':
            actions.append(tr('<a href="tool-kill:{key}" style="{link} color:{v0};">■ توقف (Kill)</a>', key=key, link=link, v0=p["danger"]))
        elif c.get('output'):
            open_ = key in expanded
            actions.append(f'<a href="tool-toggle:{key}" style="{link}">{tr("بستن ▴") if open_ else tr("نمایش خروجی ▾")}</a>')
        out.append(f'<p dir="{ui_dir()}" style="background-color:{p["surface2"]}; margin-top:6px; margin-bottom:0px; margin-left:0px; margin-right:0px;">'
                   f'&nbsp;<span style="color:{p[color_key]}; font-weight:700;">{icon}</span>&nbsp;'
                   f'<b>{html.escape(title)}</b>&nbsp;<span style="color:{p["muted"]}; {MONO} font-size:small;">{html.escape(name)}</span>'
                   f'&nbsp;·&nbsp;<span style="color:{p[color_key]};">{label}{status}</span>'
                   + ('&nbsp;&nbsp;&nbsp;' + '&nbsp;&nbsp;&nbsp;'.join(actions) if actions else '') + '</p>')
        summary = c.get('summary') or ''
        detail = summary
        if state == 'awaiting':   # the exact command / request the user is asked to approve
            args = c.get('args') or {}
            if name == 'http_request':
                extra = []
                if args.get('headers'): extra.append('headers: ' + ', '.join(f'{k}: {v}' for k, v in dict(args['headers']).items()))
                if args.get('json') is not None or args.get('body') is not None:
                    body = args.get('json') if args.get('json') is not None else args.get('body')
                    import json as _json
                    extra.append('body: ' + (body if isinstance(body, str) else _json.dumps(body, ensure_ascii=False)))
                detail = '\n'.join([summary] + extra)
            elif name == 'run_command':
                detail = f'{"cmd" if str(args.get("shell", "")).lower() == "cmd" else "PowerShell"} > {summary}\n(cwd = project folder, timeout {args.get("timeout") or 120} s)'
            elif name == 'download_file' and args.get('overwrite'):
                detail = summary + '\n(overwrite: true)'
        if detail:
            out.append(_mono_lines(detail if len(detail) < 4000 else detail[:4000] + '…', dict(p, code_bg=p['code_head'])))
        if c.get('output') and f'{mid}:{i}' in expanded and state not in ('awaiting', 'running'):
            out.append(_mono_lines(c['output'], p))
    return ''.join(out) + '<p style="margin-top:0px; margin-bottom:6px;">&nbsp;</p>'
