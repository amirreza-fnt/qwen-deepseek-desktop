"""Tests for the redesigned UI: fonts, themes, bubbles, streaming bubble, toasts, composer, provider pill."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.ui.main_window import Window, Settings
from app.ui import render, theme, icons
from app.ui.widgets import Composer

def app():
    return QApplication.instance() or QApplication([])

def test_vazirmatn_font_is_bundled_and_registered():
    app(); folder = theme.asset_dir() / 'fonts'
    assert (folder / 'Vazirmatn-Regular.ttf').exists() and (folder / 'OFL.txt').exists()
    assert theme.load_fonts() == 'Vazirmatn' and 'Vazirmatn' in QFontDatabase.families()

def test_both_themes_style_and_icons_render():
    app()
    for name in ('Light', 'Dark'):
        css = theme.stylesheet(name, 12); assert '#ComposerBox' in css and theme.palette(name)['accent'] in css
    for name in icons.PATHS: assert not icons.pixmap(name, '#123456', 18).isNull()

def test_markdown_code_highlighting_and_copy_links():
    blocks = []
    out = render.message_html('متن **پررنگ** و `x`\n\n```python\nprint("hi")\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |', blocks, theme.palette('Light'))
    assert blocks == ['x', 'print("hi")'] and 'copy-code:0' in out and 'copy-code:1' in out and 'کپی کد' in out
    assert '<strong>' in out and '<table' in out and 'color' in out  # Pygments inline styles
    assert '<script>' not in render.message_html('<script>alert(1)</script>', [], theme.palette('Light'))
    assert render.direction('سلام hello') == 'rtl' and render.direction('hello سلام') == 'ltr'

def test_streaming_bubble_receives_text_in_place(tmp_path):
    app(); store = Storage(tmp_path / 'h.db'); cid = store.create(provider='qwen'); store.add(cid, 'user', 'سلام')
    w = Window(store); w.cid = cid; w.worker = object(); w.worker_cid = cid; w.render()
    assert w.stream_cursor is not None
    w.update_preview('Hel'); w.update_preview('lo **x**'); w._flush_stream()
    text = w.chat.toPlainText(); assert 'Hello x' in text and '**' not in text and text.index('سلام') < text.index('Hello')
    w.worker = None; w.render(); assert 'Hello' not in w.chat.toPlainText(); w.close(); store.db.close()

def test_toasts_replace_modal_errors_and_offer_retry(tmp_path):
    app(); store = Storage(tmp_path / 'h.db'); w = Window(store); w.resize(1000, 700)
    calls = []; w.retry_message = lambda: calls.append(1)
    w.on_failed('خطای آزمایشی\n\nپاسخ سرور: Bad_Request', 'qwen')
    toast = w._toasts[-1]
    assert 'Bad_Request' in toast.label.text() and toast.action_button is not None and w.status.state == 'error'
    toast.action_button.click(); assert calls == [1]
    w.close(); store.db.close()

def test_composer_grows_with_content():
    app(); c = Composer(); c.resize(400, 44); c.show()
    start = c.height(); c.setPlainText('\n'.join(['line'] * 6)); QApplication.processEvents()
    assert c.height() > start and c.height() <= c.max_height
    c.setPlainText('\n'.join(['line'] * 60)); QApplication.processEvents(); assert c.height() == c.max_height

def test_theme_toggle_and_provider_pill(tmp_path):
    app(); store = Storage(tmp_path / 'h.db'); w = Window(store)
    assert w.options['theme'] == 'Light'; w.toggle_theme(); assert store.settings()['theme'] == 'Dark'
    w.build_provider_menu(); assert any('Qwen' in a.text() for a in w.provider_menu.actions())
    w.options['qwen_transport'] = 'http'; w.set_provider('qwen'); assert store.settings()['provider'] == 'qwen' and 'Qwen' in w.provider_pill.text()
    w.set_qwen_model('qwen3.8-max'); assert 'qwen3.8-max' in w.provider_pill.text()
    w.close(); store.db.close()

def test_settings_dialog_is_tabbed(tmp_path):
    app(); store = Storage(tmp_path / 'h.db'); w = Window(store); d = Settings(w, store.settings())
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == ['سرویس‌ها', 'ظاهر', 'گفت‌وگو', 'درباره']
    w.close(); store.db.close()

def test_empty_state_and_inline_code_copy(tmp_path):
    app(); store = Storage(tmp_path / 'h.db'); w = Window(store)
    assert 'چه کمکی' in w.chat.toPlainText()
    cid = store.create(); store.add(cid, 'assistant', 'از `pip install x` استفاده کنید'); w.cid = cid; w.render()
    w.copy_code_link(QUrl('copy-code:0')); assert QApplication.clipboard().text() == 'pip install x'
    w.close(); store.db.close()
