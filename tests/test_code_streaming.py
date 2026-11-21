"""Qwen tool phases, inline-code payload, fence auto-close, per-paragraph bidi and incremental streaming render."""
import json, logging, os, random, time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from app.backend.qwen_protocol import QwenStreamState, chat_payload, finish_stream, INLINE_CODE_INSTRUCTION
from app.database.storage import Storage
from app.ui.main_window import Window
from app.ui import render, theme

def app():
    return QApplication.instance() or QApplication([])

def sse(obj): return b'data: ' + json.dumps(obj).encode()

def delta(**d): return sse({'choices': [{'delta': d}]})

# ----- parser -------------------------------------------------------------------------------------------
def test_tool_call_code_and_output_become_fenced_blocks(caplog):
    page = "print('''<!DOCTYPE html>\n<html><body>سلام</body></html>''')"
    st = QwenStreamState(logging.getLogger('deepseek_desktop'))
    out = []
    with caplog.at_level(logging.INFO, logger='deepseek_desktop'):
        for line in [sse({'response.created': {'response_id': 'r1'}}),
                     delta(phase='answer', content='Here:', status='typing'),
                     delta(phase='tool_call', function_call={'name': 'code_interpreter', 'arguments': json.dumps({'code': page[:20]})}),
                     delta(phase='tool_call', function_call={'name': 'code_interpreter', 'arguments': json.dumps({'code': page})}, status='finished'),
                     delta(phase='tool_result', role='function', content='OUTPUT-1', status='finished'),
                     delta(phase='weird_new_phase!!', content='secret text'),
                     delta(phase='answer', content=' done', status='finished')]:
            out += st.feed(line)
    text = ''.join(p['content'] for p in out if p['type'] == 'text')
    assert text.startswith('Here:') and text.endswith(' done')
    assert '```python\n' + page + '\n```' in text and '```html\n<!DOCTYPE html>\n<html><body>سلام</body></html>\n```' in text
    assert '```text\nOUTPUT-1\n```' in text and 'secret text' not in text
    assert st.tool_count == 1 and finish_stream(st)['type'] == 'complete'
    logs = caplog.text
    assert 'unknown_phase=weird_new_phase' in logs and 'secret text' not in logs and 'OUTPUT-1' not in logs and 'سلام' not in logs

def test_pending_tool_flushed_at_end_and_length_is_incomplete():
    st = QwenStreamState()
    st.feed(delta(phase='answer', content='a'))
    st.feed(delta(phase='code_interpreter', content='x = 1'))
    tail = st.flush(); assert '```python\nx = 1\n```' in tail[0]['content']
    st.feed(sse({'choices': [{'delta': {'phase': 'answer', 'content': 'b'}, 'finish_reason': 'length'}]}))
    assert finish_stream(st)['type'] == 'incomplete'

def test_fences_inside_tool_output_cannot_break_the_block():
    st = QwenStreamState(); st.feed(delta(phase='tool_result', role='function', content='a\n```\nb', status='finished'))
    text = st.text; assert text.count('\n```') == 2 and 'b' in text

def test_inline_code_payload():
    msg = chat_payload('m', 'c', 'Hi', inline_code=True)['messages'][0]
    assert msg['content'] == INLINE_CODE_INSTRUCTION + '\n\nHi'
    assert msg['feature_config']['code_interpreter'] is False and msg['feature_config']['function_calling'] is False
    assert chat_payload('m', 'c', 'Hi')['messages'][0]['content'] == 'Hi'

# ----- rendering ----------------------------------------------------------------------------------------
P = theme.palette('Light')

def test_unterminated_fence_renders_as_ltr_code_block():
    blocks = []; out = render.message_html('متن\n\n```html\n<div>\n  <p>x</p>', blocks, P)
    assert blocks == ['<div>\n  <p>x</p>'] and 'copy-code:0' in out and out.count('dir="ltr" align="left"') >= 2
    assert render.MONO.split(':')[0] in out and '```' not in out

def test_per_paragraph_bidi():
    out = render.message_html('سلام دنیا\n\nHello world با فارسی\n\n- مورد\n- item', [], P)
    assert '<p dir="rtl">سلام' in out and '<p dir="ltr" align="left">Hello' in out
    assert '<li dir="rtl">مورد' in out and '<li dir="ltr" align="left">item' in out

LINES = ['<!DOCTYPE html>', '<html lang="fa" dir="rtl">', '<head>', '  <style>'] + \
        [f'    .item-{i} {{ color: #{i:06x}; }}' for i in range(2500)] + ['  </style>', '</head>', '<body><h1>سلام</h1></body>', '</html>']
REPLY = 'این **صفحه** است:\n\n```html\n' + '\n'.join(LINES) + '\n```\n\nنکته‌ها:\n\n1. اول\n2. Second\n'

def streaming_window(tmp_path):
    app(); store = Storage(tmp_path / 's.db'); cid = store.create('t', 'qwen'); store.add(cid, 'user', 'یک صفحه HTML بنویس')
    w = Window(store); w.resize(1000, 700); w.cid = cid; w.worker = object(); w.worker_cid = cid; w.render()
    return w, store, cid

def test_long_code_streams_incrementally_and_matches_final(tmp_path):
    w, store, cid = streaming_window(tmp_path)
    rng = random.Random(7); i = 0; worst = 0.0; started = time.monotonic(); mid_checked = False
    while i < len(REPLY):
        n = rng.randint(1, 300); w.update_preview(REPLY[i:i + n]); i += n
        t = time.monotonic(); w._flush_stream(); worst = max(worst, time.monotonic() - t)
        if not mid_checked and i > len(REPLY) // 2:   # mid-stream: a real code block with an open fence
            mid_checked = True; text = w.chat.toPlainText()
            assert '```' not in text and '.item-10 { color' in text and w.stream_renderer.mode == 'code'
            w.copy_code_link(QUrl('copy-stream:0'))
            assert QApplication.clipboard().text().startswith('<!DOCTYPE html>\n<html')
    total = time.monotonic() - started
    assert total < 20 and worst < 1.0, (total, worst)
    streamed = render.strip_code_pad(w.chat.toPlainText())
    assert w.stream_renderer.code_for_link(0).rstrip('\n') == '\n'.join(LINES)
    assert '\n'.join(LINES) in streamed and 'Second' in streamed and '**' not in streamed
    store.add(cid, 'assistant', REPLY); w.worker = None; w.render()
    final = render.strip_code_pad(w.chat.toPlainText())
    body = lambda t: t[t.index('این'):].replace('\u2063', '').strip()
    assert body(streamed) == body(final)
    assert w.code_blocks[0] == '\n'.join(LINES)

def test_selection_copy_drops_code_padding(tmp_path):
    w, store, cid = streaming_window(tmp_path)
    store.add(cid, 'assistant', '```python\ndef f():\n    return 1\n```'); w.worker = None; w.render()
    w.chat.selectAll(); data = w.chat.createMimeDataFromSelection()
    assert 'def f():\n    return 1' in data.text().replace('\xa0', ' ') and render.CODE_PAD not in data.text()
