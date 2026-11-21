"""Project mode in the window: folder binding (stored per conversation), prompt context, streamed progress,
review panel with diff, apply / reject / undo (temp folders only), and the greeting-safe Qwen instruction."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from app.backend.qwen_protocol import INLINE_CODE_INSTRUCTION
from app.database.storage import Storage
from app.project import core
from app.ui.main_window import Window
from app.ui import project_panel, theme

def app():
    return QApplication.instance() or QApplication([])

REPLY = ('فایل‌ها را آماده کردم.\n\n```file:src/util.py\ndef add(a, b):\n    return a + b\n```\n\n'
         '```edit:src/main.py\n<<<<<<< SEARCH\nprint("old")\n=======\nfrom util import add\nprint(add(1, 2))\n>>>>>>> REPLACE\n```\n\n'
         '```edit:src/main.py\n<<<<<<< SEARCH\nnot in the file\n=======\nx\n>>>>>>> REPLACE\n```\n')

def setup(tmp_path):
    app(); root = tmp_path / 'proj'; (root / 'src').mkdir(parents=True)
    (root / 'src' / 'main.py').write_text('print("old")\n', encoding='utf-8'); (root / 'node_modules').mkdir(); (root / 'node_modules' / 'x.js').write_text('x')
    store = Storage(tmp_path / 'p.db'); w = Window(store); w.project_panel.history_base = tmp_path / 'hist'; w.project_panel.confirm = False
    return w, store, root

def test_instruction_is_conditional_for_greetings():
    text = INLINE_CODE_INSTRUCTION
    assert 'If and only if' in text and 'never use your built-in tools' in text and 'without any code' in text and 'greetings' in text

def test_folder_binding_tree_and_prompt(tmp_path):
    w, store, root = setup(tmp_path)
    w.bind_project_folder(str(root)); cid = w.cid
    assert store.project(cid) == (str(root), True, []) and w.project_panel.isVisibleTo(w) or w.project_button.isChecked()
    rels = [r for r, _ in w.project_panel.files]; assert rels == ['src/main.py']
    w.project_panel.set_attached(['src/main.py']); assert store.project(cid)[2] == ['src/main.py']
    prompt = w.project_prompt('سلام، این را درست کن')
    assert prompt.startswith(core.PROJECT_INSTRUCTION) and 'Current content of src/main.py' in prompt and prompt.endswith('سلام، این را درست کن')
    w.project_panel.mode.setChecked(False); assert store.project(cid)[1] is False and w.project_prompt('hi') == 'hi'
    w.new_chat(); assert w.project_panel.root is None    # binding is per conversation
    w.cid = cid; w.render(); assert w.project_panel.root == str(root)

def test_stream_progress_review_apply_reject_undo(tmp_path):
    w, store, root = setup(tmp_path)
    w.bind_project_folder(str(root)); cid = w.cid
    w.update_project_progress(REPLY[:REPLY.index('return a')], final=True)
    assert 'در حال نوشتن src/util.py' in w.project_panel.progress.text()
    w.worker = object(); w.worker_cid = cid
    w.finished(REPLY, '', False, False); w.worker = None
    panel = w.project_panel; changes = panel.changes
    assert [(c.path, c.kind, c.state) for c in changes] == [('src/util.py', 'create', 'pending'), ('src/main.py', 'modify', 'error')]
    assert 'پیدا نشد' in changes[1].error and panel.tabs.currentIndex() == 1
    panel.change_list.setCurrentRow(1); assert panel.fix.isEnabled() and not panel.apply_one.isEnabled()
    panel.fix.click(); assert 'src/main.py' in w.composer.toPlainText() and 'src/main.py' in panel.attached
    panel.change_list.setCurrentRow(0); assert 'def' in panel.diff.toPlainText() and 'add' in panel.diff.toPlainText()
    assert not (root / 'src' / 'util.py').exists()          # nothing written before the click
    panel.apply_all.click()
    assert (root / 'src' / 'util.py').read_text() == 'def add(a, b):\n    return a + b\n' and changes[0].state == 'applied'
    assert (root / 'src' / 'main.py').read_text() == 'print("old")\n'   # the failed edit was not applied
    assert panel.undo.isEnabled(); panel.undo.click(); assert not (root / 'src' / 'util.py').exists() and changes[0].state == 'pending'
    panel.reject_one.click(); assert changes[0].state == 'rejected' and not panel.apply_all.isEnabled()

def test_diff_html_unified_and_side_by_side(tmp_path):
    root = tmp_path / 'r'; root.mkdir(); (root / 'a.py').write_text('x = 1\ny = 2\n')
    ch = core.plan_changes(root, core.parse_ops('```edit:a.py\n<<<<<<< SEARCH\ny = 2\n=======\ny = 3\n>>>>>>> REPLACE\n```'))[0]
    p = theme.palette('Dark')
    unified = project_panel.diff_html(ch, p); side = project_panel.diff_html(ch, p, True)
    assert 'dir="ltr"' in unified and '#12351f' in unified and '#3d1518' in unified and '<table' in side
