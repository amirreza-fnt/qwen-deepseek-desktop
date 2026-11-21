"""i18n: every translatable string has an English entry with the same placeholders, and the layout direction follows
the language (RTL for Persian, LTR for English)."""
import ast, re, string
from pathlib import Path
import pytest
from app import i18n
from app.i18n_en import EN

ROOT = Path(__file__).resolve().parents[1]
FA = re.compile('[\u0600-\u06FF]')


def tr_keys():
    keys = {}
    for f in sorted((ROOT / 'app').rglob('*.py')) + [ROOT / 'main.py']:
        tree = ast.parse(f.read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, 'id', getattr(n.func, 'attr', None)) == 'tr' and n.args:
                arg = n.args[0]
                assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), f'{f.name}:{n.lineno} tr() needs a literal'
                keys.setdefault(arg.value, f'{f.name}:{n.lineno}')
    return keys


def fields(s):
    return sorted({name for _, name, _, _ in string.Formatter().parse(s) if name is not None})


def test_every_key_has_english_and_persian():
    keys = tr_keys()
    assert len(keys) > 300
    missing = [f'{where}: {k!r}' for k, where in keys.items() if k not in EN]
    assert not missing, 'missing English translations:\n' + '\n'.join(missing)
    for k, en in EN.items():
        assert k.strip() == '' or FA.search(k) or k == ', ' or 'Language' in k, f'Persian key expected: {k!r}'
        assert en.strip() or not k.strip(), f'empty translation for {k!r}'


def test_placeholders_match():
    for k, en in EN.items():
        assert fields(k) == fields(en), f'placeholder mismatch: {k!r} -> {en!r}'


def test_english_has_no_persian_text():
    allowed = {'Language / زبان'}
    for k, en in EN.items():
        if en in allowed: continue
        assert not FA.search(en), f'untranslated: {en!r}'


def test_no_stale_translations():
    keys = tr_keys()
    stale = [k for k in EN if k not in keys]
    assert not stale, stale


def test_no_untranslated_persian_ui_literals():
    """Persian text in app/ must go through tr() (docstrings/comments excluded)."""
    offenders = []
    for f in sorted((ROOT / 'app').rglob('*.py')):
        if f.name.startswith('i18n'): continue
        tree = ast.parse(f.read_text(encoding='utf-8'))
        inside = set()
        docs = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == 'tr':
                for a in ast.walk(n.args[0]): inside.add(id(a))
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body and isinstance(n.body[0], ast.Expr):
                docs.add(id(n.body[0].value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and FA.search(n.value) and id(n) not in inside and id(n) not in docs:
                if n.value in ('فارسی',) or 'زبان' in n.value: continue
                offenders.append(f'{f.name}:{n.lineno}')
    assert not offenders, offenders


@pytest.fixture
def lang():
    yield i18n.set_language
    i18n.set_language('fa')


def test_tr_switches_language(lang):
    lang('en'); assert i18n.tr('تنظیمات') == 'Settings' and not i18n.is_rtl() and i18n.ui_dir() == 'ltr'
    assert i18n.tr('مسیر خارج از پوشهٔ پروژه است: {rel}', rel='x') == 'Path is outside the project folder: x'
    lang('fa'); assert i18n.tr('تنظیمات') == 'تنظیمات' and i18n.is_rtl() and i18n.ui_dir() == 'rtl'


def test_resolve_and_system_default(lang, monkeypatch):
    monkeypatch.setattr(i18n, 'system_language', lambda: 'en')
    assert i18n.resolve('system') == 'en' and i18n.resolve('fa') == 'fa' and i18n.resolve('xx') == 'en'
    monkeypatch.setattr(i18n, 'system_language', lambda: 'fa')
    assert i18n.resolve(None) == 'fa'
    monkeypatch.setenv('QD_LANG', 'en'); assert i18n.init_language('fa') == 'en'


def test_saved_language_setting(tmp_path):
    from app.database.storage import Storage, read_saved_setting
    db = tmp_path / 'h.sqlite3'; store = Storage(db)
    assert store.settings()['language'] == 'system'
    store.save_settings({'language': 'en'}); store.db.commit()
    assert read_saved_setting('language', path=db) == 'en'
    assert read_saved_setting('language', 'system', path=tmp_path / 'missing.sqlite3') == 'system'


def test_layout_direction_switches(lang, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.database.storage import Storage
    from app.ui.main_window import Window
    lang('en')
    w = Window(Storage(tmp_path / 'en.sqlite3'))
    assert w.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert i18n.label_alignment() == Qt.AlignmentFlag.AlignLeft
    w.close()
    lang('fa')
    w = Window(Storage(tmp_path / 'fa.sqlite3'))
    assert w.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert i18n.label_alignment() == Qt.AlignmentFlag.AlignRight
    w.close()
