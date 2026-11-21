import sys, json
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QCoreApplication
# QtWebEngine (built-in Qwen browser) must be initialised before the QApplication exists.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
try:
    import PySide6.QtWebEngineWidgets  # noqa: F401
except ImportError:
    pass
from PySide6.QtWidgets import QApplication
from app import i18n


def _pick_language():
    """Choose the UI language before any UI module is imported: --lang en|fa > QD_LANG > saved setting > OS locale."""
    if '--lang' in sys.argv:
        i = sys.argv.index('--lang')
        if i + 1 < len(sys.argv): i18n.os.environ['QD_LANG'] = sys.argv[i + 1]; del sys.argv[i:i + 2]
    from app.database.storage import read_saved_setting
    return i18n.init_language(read_saved_setting('language'))


_pick_language()
from app.ui.main_window import Window, credential, token_required  # noqa: E402

def L(fa, en):
    """Sample content for previews in the current UI language."""
    return en if i18n.language() == 'en' else fa

def qwen_browser_smoke(app, window, target):
    """Diagnostic: load chat.qwen.ai in the built-in browser, save a screenshot and a JSON summary."""
    result = {'webengine': False}
    browser = window.get_qwen_browser()
    def write():
        Path(target).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        window.close(); app.quit()
    if browser is None: write(); return
    result['webengine'] = True
    browser.show_window(window, 'smoke test'); browser.dialog.resize(1100, 800)
    def loaded(ok):
        result['load_ok'] = bool(ok); result['url_host'] = browser.page.url().host(); result['title'] = browser.page.title()
        def shot():
            image = Path(target).with_suffix('.png'); result['screenshot'] = str(image) if browser.dialog.view.grab().save(str(image)) else None
            browser.token_present(lambda present: (result.__setitem__('logged_in', present), write()))
        QTimer.singleShot(3000, shot)
    if browser.loaded: loaded(True)
    else: browser.page.loadFinished.connect(loaded)
    QTimer.singleShot(60000, lambda: (result.setdefault('load_ok', 'timeout'), write()))

SAMPLE_EN = [
    ('user', 'Hi! Write a Python function that computes a factorial.'),
    ('assistant', 'Sure! Here is a simple **recursive** implementation:\n\n```python\ndef factorial(n: int) -> int:\n    \"\"\"Return n! for n >= 0.\"\"\"\n    if n < 2:\n        return 1\n    return n * factorial(n - 1)\n\nprint(factorial(5))  # 120\n```\n\nNotes:\n\n- For large `n`, prefer `math.factorial`.\n- An iterative version avoids stack overflow.'),
    ('user', 'Thanks, now show the iterative version too.'),
    ('assistant', 'Iterative version:\n\n```python\ndef factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result\n```'),
]

SAMPLE = [
    ('user', 'سلام! یک تابع پایتون بنویس که فاکتوریل را حساب کند.'),
    ('assistant', 'حتماً! این یک پیاده‌سازی ساده و **بازگشتی** است:\n\n```python\ndef factorial(n: int) -> int:\n    \"\"\"Return n! for n >= 0.\"\"\"\n    if n < 2:\n        return 1\n    return n * factorial(n - 1)\n\nprint(factorial(5))  # 120\n```\n\nنکته‌ها:\n\n- برای `n` بزرگ بهتر است از `math.factorial` استفاده کنید.\n- نسخهٔ حلقه‌ای از سرریز پشته جلوگیری می‌کند.'),
    ('user', 'ممنون، حالا نسخهٔ حلقه‌ای را هم نشان بده.'),
    ('assistant', 'نسخهٔ حلقه‌ای:\n\n```python\ndef factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result\n```'),
]

def ui_preview(target, theme_name='Light'):
    """Render the main window with sample messages (temporary database) and save a screenshot."""
    import tempfile
    from app.database.storage import Storage
    app=QApplication(sys.argv); app.setApplicationName('Qwen DeepSeek Desktop')
    tmp=tempfile.mkdtemp(prefix='ui-preview-'); store=Storage(Path(tmp)/'preview.sqlite3')
    store.save_settings(dict(store.settings(), theme=theme_name, light_blue_migration=True, provider='qwen', qwen_transport='http'))
    for title in L(('برنامه‌ریزی سفر شمال', 'خلاصهٔ مقاله یادگیری ماشین', 'ایده‌های نام برای استارتاپ'), ('Weekend trip plan', 'ML paper summary', 'Startup name ideas')): store.create(title, 'deepseek')
    cid=store.create(L('تابع فاکتوریل در پایتون', 'Factorial function in Python'), 'qwen')
    for role, text in L(SAMPLE, SAMPLE_EN): store.add(cid, role, text)
    window=Window(store); window.resize(1280, 820); window.cid=cid; window.refresh_list(); window.render(); window.show()
    def shot():
        window.notify(i18n.tr('کد کپی شد'), 'success')
        QTimer.singleShot(400, lambda: (window.grab().save(target), window.close(), app.quit()))
    QTimer.singleShot(600, shot); app.exec()

def stream_reply(lines=2500):
    css = '\n'.join(f'    .card-{i} {{ color: #{(i * 2654435761) % 0xFFFFFF:06x}; padding: {i % 9}px; border-radius: 8px; }}' for i in range(lines))
    page = ('<!DOCTYPE html>\n<html lang="fa" dir="rtl">\n<head>\n  <meta charset="UTF-8">\n  <title>فروشگاه</title>\n  <style>\n'
            '    body { font-family: Vazirmatn, sans-serif; margin: 0; background: #f8fafc; }\n' + css + '\n  </style>\n</head>\n<body>\n'
            '  <header class="hero">\n    <h1>فروشگاه آنلاین</h1>\n    <button onclick="alert(\'سلام\')">شروع</button>\n  </header>\n'
            '  <script>\n    document.querySelectorAll(".card-1").forEach(el => el.classList.add("on"));\n  </script>\n</body>\n</html>')
    return ('حتماً! این یک صفحهٔ **کامل** HTML است که مستقیم داخل چت نوشته می‌شود (بدون ابزار):\n\n```html\n' + page +
            '\n```\n\nنکته‌ها:\n\n- فایل را با نام `index.html` ذخیره کنید.\n- Works in any modern browser, بدون نیاز به سرور.\n')

def ui_preview_stream(prefix, theme_name='Light'):
    """Simulate a long streamed reply (temporary database, no network) through the real throttled streaming path and
    save screenshots: <prefix>_early.png, <prefix>_mid.png (mid-stream, open code fence) and <prefix>_final.png."""
    import tempfile, time, random
    from app.database.storage import Storage
    app=QApplication(sys.argv); app.setApplicationName('Qwen DeepSeek Desktop')
    tmp=tempfile.mkdtemp(prefix='ui-preview-'); store=Storage(Path(tmp)/'preview.sqlite3')
    store.save_settings(dict(store.settings(), theme=theme_name, light_blue_migration=True, provider='qwen', qwen_transport='http'))
    cid=store.create(L('صفحهٔ HTML فروشگاه', 'Shop HTML page'), 'qwen'); store.add(cid, 'user', L('یک صفحهٔ HTML کامل و طولانی برای فروشگاه بنویس، همه را داخل چت.', 'Write a complete, long HTML page for a shop, all inside the chat.'))
    window=Window(store); window.resize(1280, 820); window.cid=cid; window.refresh_list()
    window.worker=object(); window.worker_cid=cid; window.render(); window.show()
    reply=stream_reply(); rng=random.Random(3); state={'i': 0, 'shots': set(), 'start': time.monotonic(), 'ticks': [], 'last': time.monotonic()}
    def tick():
        now=time.monotonic(); state['ticks'].append(now-state['last']); state['last']=now
        i=state['i']; n=rng.randint(20, 160); window.update_preview(reply[i:i+n]); state['i']=i+n
        for name, at in (('early', 0.012), ('mid', 0.5)):
            if name not in state['shots'] and state['i'] > len(reply)*at:
                state['shots'].add(name); window._flush_stream(); bar=window.chat.verticalScrollBar()
                if name=='early': bar.setValue(0)   # show the start of the reply (heading + open code block)
                app.processEvents(); window.grab().save(f'{prefix}_{name}.png'); bar.setValue(bar.maximum())
        if state['i'] < len(reply): QTimer.singleShot(5, tick)
        else: QTimer.singleShot(200, done)
    def done():
        streamed=time.monotonic()-state['start']; store.add(cid, 'assistant', reply)
        t=time.monotonic(); window.finished(reply, None, False, False); final=time.monotonic()-t
        window.worker=None
        stats={'reply_chars': len(reply), 'reply_lines': reply.count('\n'), 'stream_seconds': round(streamed, 2),
               'max_event_gap_seconds': round(max(state['ticks']), 3), 'final_render_seconds': round(final, 3)}
        Path(prefix + '_stats.json').write_text(json.dumps(stats), encoding='utf-8')
        QTimer.singleShot(300, lambda: (window.grab().save(f'{prefix}_final.png'), window.close(), app.quit()))
    QTimer.singleShot(400, tick); app.exec()

PROJECT_REPLY_EN = '''I created `utils.js` and wired the button in `index.html` to it:

```file:src/utils.js
export function formatPrice(value) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
}
```

```edit:src/index.html
<<<<<<< SEARCH
    <button id="buy">Buy</button>
=======
    <button id="buy" class="primary">Buy</button>
    <p id="price"></p>
    <script type="module">
      import { formatPrice } from './utils.js';
      document.getElementById('price').textContent = formatPrice(49.9);
    </script>
>>>>>>> REPLACE
```

```edit:src/style.css
<<<<<<< SEARCH
.card { padding: 8px; }
=======
.card { padding: 16px; border-radius: 12px; }
.primary { background: #4f46e5; color: white; }
>>>>>>> REPLACE
```
'''

PROJECT_REPLY = '''فایل `utils.js` را ساختم و دکمه را در `index.html` به آن وصل کردم:

```file:src/utils.js
export function formatPrice(value) {
  return new Intl.NumberFormat('fa-IR').format(value) + ' تومان';
}
```

```edit:src/index.html
<<<<<<< SEARCH
    <button id="buy">خرید</button>
=======
    <button id="buy" class="primary">خرید</button>
    <p id="price"></p>
    <script type="module">
      import { formatPrice } from './utils.js';
      document.getElementById('price').textContent = formatPrice(250000);
    </script>
>>>>>>> REPLACE
```

```edit:src/style.css
<<<<<<< SEARCH
.card { padding: 8px; }
=======
.card { padding: 16px; border-radius: 12px; }
.primary { background: #4f46e5; color: white; }
>>>>>>> REPLACE
```
'''

def ui_preview_project(prefix, theme_name='Light'):
    """Project mode preview with a temporary project folder and database: <prefix>_files.png (file tree) and
    <prefix>_review.png (proposed changes with a diff)."""
    import tempfile
    from app.database.storage import Storage
    app=QApplication(sys.argv); app.setApplicationName('Qwen DeepSeek Desktop')
    tmp=Path(tempfile.mkdtemp(prefix='ui-preview-')); root=tmp/'shop-site'; (root/'src').mkdir(parents=True); (root/'node_modules'/'lib').mkdir(parents=True)
    (root/'src'/'index.html').write_text(L('<!DOCTYPE html>\n<html lang="fa" dir="rtl">\n<head>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <div class="card">\n    <h1>فروشگاه</h1>\n    <button id="buy">خرید</button>\n  </div>\n</body>\n</html>\n',
                                           '<!DOCTYPE html>\n<html lang="en">\n<head>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <div class="card">\n    <h1>Shop</h1>\n    <button id="buy">Buy</button>\n  </div>\n</body>\n</html>\n'), encoding='utf-8')
    reply=L(PROJECT_REPLY, PROJECT_REPLY_EN)
    (root/'src'/'style.css').write_text('body { font-family: Vazirmatn; }\n.card { padding: 8px; }\n', encoding='utf-8')
    (root/'README.md').write_text('# Shop\n', encoding='utf-8'); (root/'package.json').write_text('{"name": "shop"}\n', encoding='utf-8')
    (root/'node_modules'/'lib'/'x.js').write_text('x'); (root/'.gitignore').write_text('node_modules/\n')
    store=Storage(tmp/'preview.sqlite3')
    store.save_settings(dict(store.settings(), theme=theme_name, light_blue_migration=True, provider='qwen', qwen_transport='http'))
    window=Window(store); window.project_panel.history_base=tmp/'history'; window.resize(1500, 900)
    window.bind_project_folder(str(root)); cid=window.cid
    store.execute('UPDATE conversations SET title=? WHERE id=?', (L('دکمهٔ خرید با قیمت', 'Buy button with price'), cid))
    window.project_panel.set_attached(['src/index.html', 'src/style.css'])
    store.add(cid, 'user', L('یک تابع قالب‌بندی قیمت بساز و قیمت را زیر دکمهٔ خرید نشان بده. @index.html', 'Create a price formatting function and show the price under the Buy button. @index.html')); store.add(cid, 'assistant', reply)
    window.refresh_list(); window.render(); window.show(); window.splitter.setSizes([250, 600, 650])
    def hide_toasts():
        for t in list(getattr(window, '_toasts', [])): t.hide()
    def files():
        hide_toasts(); window.grab().save(f'{prefix}_files.png'); window.review_project_reply(reply)
        window.project_panel.change_list.setCurrentRow(1); QTimer.singleShot(400, review)
    def review():
        hide_toasts(); window.grab().save(f'{prefix}_review.png'); window.project_panel.side.setChecked(True)
        QTimer.singleShot(300, lambda: (hide_toasts(), window.grab().save(f'{prefix}_review_side.png'), window.close(), app.quit()))
    QTimer.singleShot(700, files); app.exec()

AGENT_REPLY_EN = ('First I will look at the project structure and the logo, then run the tests.\n\n```tool:list_dir\n{"path": ".", "depth": 2}\n```\n\n'
                  '```tool:image_info\n{"path": "img/logo.png"}\n```\n\n```tool:run_command\n{"command": "npm test"}\n```\n')

AGENT_REPLY = ('اول ساختار پروژه و لوگو را بررسی می‌کنم و بعد تست‌ها را اجرا می‌کنم.\n\n```tool:list_dir\n{"path": ".", "depth": 2}\n```\n\n'
               '```tool:image_info\n{"path": "img/logo.png"}\n```\n\n```tool:run_command\n{"command": "npm test"}\n```\n')

def ui_preview_agent(prefix, theme_name='Light'):
    """Agent tool cards preview (temporary project and database; nothing is sent and the command is NOT run):
    <prefix>_agent.png with finished read-only tools (one expanded) and a command waiting for approval."""
    import tempfile, struct
    from app.database.storage import Storage
    app=QApplication(sys.argv); app.setApplicationName('Qwen DeepSeek Desktop')
    tmp=Path(tempfile.mkdtemp(prefix='ui-preview-')); root=tmp/'shop-site'; (root/'src').mkdir(parents=True); (root/'img').mkdir()
    (root/'src'/'index.html').write_text(L('<h1>فروشگاه</h1>\n', '<h1>Shop</h1>\n'), encoding='utf-8'); (root/'src'/'app.js').write_text('export const x = 1;\n', encoding='utf-8')
    (root/'package.json').write_text('{"name": "shop", "scripts": {"test": "node --test"}}\n', encoding='utf-8')
    (root/'img'/'logo.png').write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>IIBBBBB',512,256,8,6,0,0,0)+b'\x00'*40)
    store=Storage(tmp/'preview.sqlite3')
    store.save_settings(dict(store.settings(), theme=theme_name, light_blue_migration=True, provider='qwen', qwen_transport='http'))
    window=Window(store); window.resize(1500, 900); window.start=lambda *a, **k: None
    window.bind_project_folder(str(root)); cid=window.cid
    store.execute('UPDATE conversations SET title=? WHERE id=?', (L('بررسی پروژه و اجرای تست', 'Review project and run tests'), cid))
    reply=L(AGENT_REPLY, AGENT_REPLY_EN)
    store.add(cid, 'user', L('ساختار پروژه را ببین، لوگو را بررسی کن و تست‌ها را اجرا کن.', 'Look at the project structure, check the logo and run the tests.')); store.add(cid, 'assistant', reply)
    window.refresh_list(); window.render(); window.show(); window.splitter.setSizes([250, 850, 400])
    def run_tools():
        window.agent_after_reply(reply); QTimer.singleShot(1500, shot)
    def shot():
        mid=window.agent['mid'] if window.agent else 0
        window.tool_expanded.add(f'{mid}:0'); window.render()
        for t in list(window._toasts): t.hide()
        window.grab().save(f'{prefix}_agent.png'); window.stop_agent(quiet=True); window.close(); app.quit()
    QTimer.singleShot(700, run_tools); app.exec()

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == '--ui-preview-agent':
        ui_preview_agent(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'Light'); return
    if len(sys.argv) >= 3 and sys.argv[1] == '--ui-preview-project':
        ui_preview_project(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'Light'); return
    if len(sys.argv) >= 3 and sys.argv[1] == '--ui-preview-stream':
        ui_preview_stream(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'Light'); return
    if len(sys.argv) >= 3 and sys.argv[1] == '--ui-preview':
        ui_preview(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'Light'); return
    app=QApplication(sys.argv); app.setApplicationName('Qwen DeepSeek Desktop'); window=Window(); window.show()
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        def finish_test():
            Path(sys.argv[2]).write_text('startup ok', encoding='utf-8')
            window.close(); app.quit()
        QTimer.singleShot(250, finish_test)
    elif len(sys.argv) == 3 and sys.argv[1] == '--qwen-browser-smoke':
        QTimer.singleShot(250, lambda: qwen_browser_smoke(app, window, sys.argv[2]))
    else:
        provider=window.options.get('provider','deepseek')
        try:
            if token_required(provider, window.options) and not credential(provider): window.open_settings()
        except Exception:
            if token_required(provider, window.options): window.open_settings()
    sys.exit(app.exec())
if __name__ == '__main__': main()
