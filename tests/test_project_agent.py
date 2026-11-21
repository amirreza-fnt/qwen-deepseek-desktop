"""Project-mode agent loop in the window: tool rounds after a reply, automatic read-only tools, approval cards
(approve / reject), Kill, Stop, step cap, greeting stays tool-free, and results sent back as the next message.
No network and no real provider: ``start`` is replaced by a recorder and the credential lookup is stubbed."""
import json, os, sys, time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from app.database.storage import Storage
from app.project import tools as T
from app.ui import main_window
from app.ui.main_window import Window


def app():
    return QApplication.instance() or QApplication([])


def py(code):
    return (f'& "{sys.executable}" -c "{code}"' if os.name == 'nt' else f'"{sys.executable}" -c "{code}"')


@pytest.fixture
def win(tmp_path, monkeypatch):
    app(); monkeypatch.setattr(main_window, 'credential', lambda provider='deepseek': 'test-token-not-real')
    root = tmp_path / 'proj'; (root / 'src').mkdir(parents=True)
    (root / 'src' / 'app.js').write_text('function hello() {\n  return 1;\n}\n', encoding='utf-8'); (tmp_path / 'secret.txt').write_text('x')
    w = Window(Storage(tmp_path / 'a.db')); w.project_panel.history_base = tmp_path / 'hist'; w.project_panel.confirm = False
    w.bind_project_folder(str(root)); sent = []
    w.start = lambda token, row, text, **kw: sent.append((text, kw))
    return w, root, sent


def reply(w, text):
    w.worker_cid = w.cid; w.finished(text, '', False, False)


def settle(w, timeout=40):
    end = time.monotonic() + timeout
    while w.tool_runner is not None and time.monotonic() < end:
        app().processEvents(); time.sleep(0.01)
    for _ in range(5): app().processEvents()


def tool_rows(w):
    return [r for r in w.store.messages(w.cid) if r['role'] == 'tool']


def test_prompt_mentions_tools_only_when_enabled(win):
    w, root, sent = win
    assert 'run_command' in w.project_prompt('ساختار را ببین') and 'Do NOT use tools for greetings' in w.project_prompt('سلام')
    w.project_panel.tools.setChecked(False); assert 'run_command' not in w.project_prompt('x'); assert w.options['project_tools'] is False


def test_greeting_reply_runs_no_tools(win):
    w, root, sent = win
    reply(w, 'سلام! چطور می‌تونم کمک کنم؟')
    assert w.agent is None and tool_rows(w) == [] and sent == []


def test_read_only_tools_run_automatically_and_results_are_sent(win):
    w, root, sent = win
    reply(w, 'بررسی می‌کنم.\n```tool:list_dir\n{"path": "."}\n```\n```tool:read_file\n{"path": "src/app.js"}\n```\n```tool:read_file\n{"path": "../secret.txt"}\n```')
    settle(w)
    calls = __import__('json').loads(tool_rows(w)[0]['content'])['calls']
    assert [c['state'] for c in calls] == ['done', 'done', 'error'] and 'مسیر رد شد' in calls[2]['output']
    assert len(sent) == 1 and sent[0][1]['raw'] is True and sent[0][1]['user_id'] == tool_rows(w)[0]['id']
    text = sent[0][0]
    assert text.startswith('[Tool results') and 'function hello' in text and 'src/' in text and w.agent is None
    assert 'tool-toggle:' in w.chat.toHtml()   # collapsible cards
    w.copy_code_link(QUrl(f'tool-toggle:{tool_rows(w)[0]["id"]}:1')); assert 'function hello' in w.chat.toPlainText()


def test_command_needs_approval_reject_then_approve(win):
    w, root, sent = win
    reply(w, '```tool:run_command\n{"command": "del src\\\\app.js"}\n```'); settle(w)
    mid = tool_rows(w)[0]['id']
    assert w.agent['record']['calls'][0]['state'] == 'awaiting' and w.tool_runner is None and sent == []
    assert f'tool-approve:{mid}:0' in w.chat.toHtml() and 'del src' in w.chat.toPlainText()     # exact command on the card
    w.copy_code_link(QUrl(f'tool-reject:{mid}:0')); settle(w)
    assert (root / 'src' / 'app.js').exists() and len(sent) == 1 and 'rejected by the user' in sent[0][0]
    reply(w, '```tool:run_command\n' + json.dumps({'command': py('print(40+2)')}) + '\n```'); settle(w)
    mid = tool_rows(w)[-1]['id']; assert w.agent['record']['calls'][0]['state'] == 'awaiting'
    w.copy_code_link(QUrl(f'tool-approve:{mid}:0')); settle(w)
    assert len(sent) == 2 and '42' in sent[1][0] and 'exit code: 0' in sent[1][0]


def test_session_toggle_allows_read_only_commands(win):
    w, root, sent = win
    w.project_panel.allow_ro.setChecked(True)
    reply(w, '```tool:run_command\ngit --version\n```'); settle(w)
    assert w.agent is None and len(sent) == 1        # ran without a card (git may be missing: then an error result)
    reply(w, '```tool:run_command\nnpm install\n```'); settle(w)
    assert w.agent['record']['calls'][0]['state'] == 'awaiting'


def test_kill_and_stop(win):
    w, root, sent = win
    reply(w, '```tool:run_command\n' + json.dumps({'command': py('import time; time.sleep(60)')}) + '\n```')
    mid = tool_rows(w)[0]['id']; w.copy_code_link(QUrl(f'tool-approve:{mid}:0'))
    assert w.tool_runner is not None and w.stop.isVisibleTo(w)
    time.sleep(0.5); w.copy_code_link(QUrl(f'tool-kill:{mid}:0')); settle(w)
    assert len(sent) == 1 and 'Stopped by the user (killed)' in sent[0][0]
    reply(w, '```tool:download_file\n{"url": "https://example.com/a.png"}\n```\n```tool:list_dir\n{}\n```')
    assert w.agent['record']['calls'][0]['state'] == 'awaiting'
    w.stop_request()
    assert w.agent is None and len(sent) == 1
    calls = __import__('json').loads(tool_rows(w)[-1]['content'])['calls']; assert [c['state'] for c in calls] == ['skipped', 'skipped']
    assert not (root / 'downloads').exists()


def test_step_cap(win):
    w, root, sent = win
    w.agent_steps[w.cid] = T.MAX_STEPS
    reply(w, '```tool:list_dir\n{}\n```'); settle(w)
    assert w.agent is None and tool_rows(w) == [] and sent == []


def test_tools_disabled_or_project_off(win):
    w, root, sent = win
    w.project_panel.tools.setChecked(False); reply(w, '```tool:list_dir\n{}\n```'); assert tool_rows(w) == []
    w.project_panel.tools.setChecked(True); w.project_panel.mode.setChecked(False); reply(w, '```tool:list_dir\n{}\n```'); assert tool_rows(w) == []


def test_edit_tools_go_to_review_panel_without_extra_turn(win):
    w, root, sent = win
    reply(w, 'تابع را به فایل جدا منتقل می‌کنم.\n```tool:move_lines\n{"from": "src/app.js", "start": 1, "end": 3, "to": "src/hello.js"}\n```')
    settle(w)
    panel = w.project_panel
    assert sorted((c.path, c.kind) for c in panel.changes) == [('src/app.js', 'modify'), ('src/hello.js', 'create')]
    assert sent == [] and w.agent is None                       # nothing to report back: the user reviews the diff
    assert not (root / 'src' / 'hello.js').exists()             # nothing written before «اعمال»
    calls = json.loads(tool_rows(w)[0]['content'])['calls']; assert calls[0]['state'] == 'done' and 'moved 3 lines' in calls[0]['output']
    panel.apply_all.click()
    assert (root / 'src' / 'hello.js').read_text() == 'function hello() {\n  return 1;\n}\n' and (root / 'src' / 'app.js').read_text() == ''


def test_failed_edit_tool_is_reported_to_the_model(win):
    w, root, sent = win
    reply(w, '```tool:delete_lines\n{"path": "src/app.js", "start": 1, "end": 2, "end_marker": "nope"}\n```')
    settle(w)
    assert len(sent) == 1 and 'end_marker' in sent[0][0] and '-> error' in sent[0][0]


def test_mixed_turn_builds_one_batch(win):
    w, root, sent = win
    reply(w, '```tool:insert_text\n{"path": "src/app.js", "position": "start", "text": "// header"}\n```\n```tool:read_file\n{"path": "src/app.js"}\n```')
    settle(w)
    assert len(sent) == 1 and 'PROPOSED' in sent[0][0] and '1| // header' in sent[0][0]   # the model sees its pending edit
    reply(w, '```tool:insert_text\n{"path": "src/app.js", "position": "end", "text": "// footer"}\n```'); settle(w)
    ch = w.project_panel.changes
    assert len(ch) == 1 and ch[0].new == '// header\nfunction hello() {\n  return 1;\n}\n// footer\n'
