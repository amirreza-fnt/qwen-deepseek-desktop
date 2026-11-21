"""Colour palettes, the application style sheet and the bundled Vazirmatn font."""
import os, sys
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QFont

FONT_FAMILY = 'Vazirmatn'

PALETTES = {
    'Light': dict(
        bg='#f6f7fb', sidebar='#eef1f7', surface='#ffffff', surface2='#f1f4f9', border='#e1e6ef', border_strong='#cdd5e1',
        text='#1b2433', muted='#6b768a', accent='#4f46e5', accent_hover='#4338ca', accent_soft='#eceafe', accent_text='#ffffff',
        user_bubble='#4f46e5', user_text='#ffffff', bot_bubble='#ffffff', bot_border='#e4e8f0',
        code_bg='#0f172a', code_head='#1e293b', code_text='#e2e8f0', inline_code='#eef1f6', link='#4f46e5',
        danger='#dc2626', danger_soft='#fdecec', success='#059669', warning='#d97706', selection='#c7d2fe', icon='#475569',
        scroll='#c9d1de'),
    'Dark': dict(
        bg='#0f1117', sidebar='#141720', surface='#1a1e29', surface2='#212634', border='#262c3a', border_strong='#343c4f',
        text='#e6e9f0', muted='#8b93a7', accent='#7c74ff', accent_hover='#9089ff', accent_soft='#262448', accent_text='#ffffff',
        user_bubble='#5b54e8', user_text='#ffffff', bot_bubble='#1a1e29', bot_border='#262c3a',
        code_bg='#0b0e14', code_head='#161b26', code_text='#e2e8f0', inline_code='#262b38', link='#a5a0ff',
        danger='#f87171', danger_soft='#3a1f24', success='#34d399', warning='#fbbf24', selection='#3b3780', icon='#a7b0c2',
        scroll='#343c4f'),
}

def palette(theme):
    return PALETTES.get(theme, PALETTES['Light'])

def asset_dir():
    """app/assets both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent.parent))
    for candidate in (base / 'app' / 'assets', Path(__file__).resolve().parent.parent / 'assets'):
        if candidate.exists(): return candidate
    return base / 'app' / 'assets'

_loaded = []

def load_fonts():
    """Register the bundled Vazirmatn font (SIL OFL 1.1). Returns the family name, or '' if unavailable."""
    if _loaded: return _loaded[0]
    family = ''
    folder = asset_dir() / 'fonts'
    for name in ('Vazirmatn-Regular.ttf', 'Vazirmatn-Medium.ttf', 'Vazirmatn-Bold.ttf'):
        path = folder / name
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0 and not family:
                families = QFontDatabase.applicationFontFamilies(fid); family = families[0] if families else ''
    _loaded.append(family)
    return family

def stylesheet(theme, font_pt=12):
    p = palette(theme); f = FONT_FAMILY
    return f"""
* {{ font-family: '{f}', 'Segoe UI', 'Tahoma'; }}
QMainWindow, QDialog {{ background: {p['bg']}; color: {p['text']}; }}
QWidget {{ color: {p['text']}; font-size: {font_pt}pt; }}
QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px 8px; border-radius: 6px; }}
#Sidebar {{ background: {p['sidebar']}; border-left: 1px solid {p['border']}; }}
#Main {{ background: {p['bg']}; }}
#Brand {{ font-size: {font_pt + 3}pt; font-weight: 700; }}
#BrandSub, #Muted {{ color: {p['muted']}; font-size: {max(font_pt - 2, 8)}pt; }}
#Header {{ background: {p['bg']}; border-bottom: 1px solid {p['border']}; }}
#ChatTitle {{ font-size: {font_pt + 2}pt; font-weight: 700; }}
QLineEdit, QSpinBox, QComboBox {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 7px 10px; selection-background-color: {p['selection']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']}; selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; outline: none; padding: 4px; }}
#SearchBox {{ background: {p['surface']}; border-radius: 12px; padding: 8px 10px; }}
QPushButton {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 8px 14px; }}
QPushButton:hover {{ border-color: {p['border_strong']}; background: {p['surface2']}; }}
QPushButton:pressed {{ background: {p['accent_soft']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p['muted']}; }}
#Primary {{ background: {p['accent']}; color: {p['accent_text']}; border: none; font-weight: 600; padding: 10px 14px; }}
#Primary:hover {{ background: {p['accent_hover']}; }}
#Primary:disabled {{ background: {p['border_strong']}; color: {p['surface']}; }}
QToolButton {{ background: transparent; border: none; border-radius: 9px; padding: 6px; }}
QToolButton:hover {{ background: {p['surface2']}; }}
QToolButton:checked {{ background: {p['accent_soft']}; color: {p['accent']}; }}
#Chip {{ border: 1px solid {p['border']}; border-radius: 14px; padding: 4px 10px; color: {p['muted']}; }}
#Chip:checked {{ border-color: {p['accent']}; color: {p['accent']}; background: {p['accent_soft']}; }}
#Ghost {{ color: {p['muted']}; padding: 4px 8px; }}
#Ghost:hover {{ color: {p['text']}; }}
#Pill {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 16px; padding: 6px 12px; font-weight: 600; }}
#Pill:hover {{ border-color: {p['accent']}; }}
#Pill::menu-indicator {{ image: none; width: 0; }}
#SendButton {{ background: {p['accent']}; border-radius: 18px; padding: 0; }}
#SendButton:hover {{ background: {p['accent_hover']}; }}
#SendButton:disabled {{ background: {p['border_strong']}; }}
#StopButton {{ background: {p['text']}; border-radius: 18px; padding: 0; }}
#ComposerBox {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 18px; }}
#ComposerBox[focused="true"] {{ border-color: {p['accent']}; }}
#Composer {{ background: transparent; border: none; padding: 4px 2px; selection-background-color: {p['selection']}; }}
QListWidget#ChatList {{ background: transparent; border: none; outline: none; padding: 2px; }}
QListWidget#ChatList::item {{ padding: 9px 10px; border-radius: 10px; margin: 1px 0; color: {p['text']}; }}
QListWidget#ChatList::item:hover {{ background: {p['surface2']}; }}
QListWidget#ChatList::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QTextBrowser#Chat {{ background: {p['bg']}; border: none; padding: 0 6px; selection-background-color: {p['selection']}; }}
QTextEdit {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['scroll']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['scroll']}; border-radius: 4px; min-width: 30px; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background: {p['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; margin: 0 2px; border-bottom: 2px solid transparent; color: {p['muted']}; }}
QTabBar::tab:selected {{ color: {p['accent']}; border-bottom-color: {p['accent']}; font-weight: 600; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 12px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; right: 12px; color: {p['muted']}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p['border_strong']}; background: {p['surface']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 7px; }}
QMenu::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
QMessageBox {{ background: {p['surface']}; }}
#Toast {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
#Toast[kind="error"] {{ border-color: {p['danger']}; background: {p['danger_soft']}; }}
#Toast[kind="success"] {{ border-color: {p['success']}; }}
#ToastText {{ background: transparent; }}
#StatusDot {{ border-radius: 4px; }}
#Banner {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px; }}
"""
