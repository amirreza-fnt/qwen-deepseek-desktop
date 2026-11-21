"""Tiny i18n layer: English and Persian (فارسی).

Source strings are written in Persian (the app's original language) and wrapped in ``tr()``.
``tr()`` returns the Persian text unchanged when the UI language is ``fa`` and the English
translation from :mod:`app.i18n_en` when it is ``en``. Placeholders use ``str.format`` names::

    tr('فایل {path} پیدا نشد', path=p)

The language is chosen once at startup (``init_language``) from the saved setting or, when the
setting is ``system``, from the OS locale. Changing it in Settings takes effect after a restart.
"""
from __future__ import annotations
import locale, os

LANGUAGES = {'en': 'English', 'fa': 'فارسی'}
_lang = 'fa'


def system_language() -> str:
    """'fa' when the OS locale is Persian, otherwise 'en'."""
    candidates = [os.environ.get(k, '') for k in ('LC_ALL', 'LC_MESSAGES', 'LANG')]
    try:
        from PySide6.QtCore import QLocale
        candidates.insert(0, QLocale.system().name())
    except Exception:  # pragma: no cover - Qt missing
        pass
    try:
        candidates.append(locale.getlocale()[0] or '')
    except Exception:  # pragma: no cover
        pass
    for c in candidates:
        c = (c or '').lower()
        if c.startswith('fa') or c.startswith('persian') or c.startswith('farsi'):
            return 'fa'
    return 'en'


def resolve(setting: str | None) -> str:
    setting = (setting or 'system').lower()
    return setting if setting in LANGUAGES else system_language()


def set_language(code: str) -> str:
    global _lang
    _lang = resolve(code)
    return _lang


def init_language(setting: str | None = None) -> str:
    """Pick the UI language: env QD_LANG > saved setting > OS locale."""
    return set_language(os.environ.get('QD_LANG') or setting or 'system')


def language() -> str:
    return _lang


def is_rtl() -> bool:
    return _lang == 'fa'


def ui_dir() -> str:
    """HTML ``dir`` value for UI-language text."""
    return 'rtl' if is_rtl() else 'ltr'


def ui_align() -> str:
    """HTML ``align`` value for the start edge."""
    return 'right' if is_rtl() else 'left'


def layout_direction():
    from PySide6.QtCore import Qt
    return Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight


def label_alignment():
    from PySide6.QtCore import Qt
    return Qt.AlignmentFlag.AlignRight if is_rtl() else Qt.AlignmentFlag.AlignLeft


def tr(_text: str, /, **kw) -> str:
    """Translate a Persian source string into the current UI language and fill placeholders."""
    if _lang == 'en':
        from app.i18n_en import EN
        out = EN.get(_text, _text)
    else:
        out = _text
    return out.format(**kw) if kw else out
