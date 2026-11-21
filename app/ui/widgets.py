"""Reusable widgets for the modern UI: auto-growing composer, toast notifications, status indicator."""
from app.i18n import tr, layout_direction, label_alignment, ui_dir, ui_align
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import QTextEdit, QFrame, QHBoxLayout, QLabel, QToolButton, QPushButton, QWidget, QGraphicsOpacityEffect
from app.ui import icons

class Composer(QTextEdit):
    """Message box: Enter sends, Shift+Enter adds a line; grows with its content up to ``max_lines``."""
    send = Signal()
    def __init__(self, parent=None, min_height=44, max_height=200):
        super().__init__(parent); self.min_height = min_height; self.max_height = max_height
        self.setObjectName('Composer'); self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().documentLayout().documentSizeChanged.connect(self._grow)
        self.setFixedHeight(min_height)
    def _grow(self, *_):
        height = int(self.document().size().height() + self.contentsMargins().top() + self.contentsMargins().bottom() + 10)
        self.setFixedHeight(max(self.min_height, min(self.max_height, height)))
    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier): self.send.emit()
        else: super().keyPressEvent(e)
    def focusInEvent(self, e):
        super().focusInEvent(e); self._set_focus_prop(True)
    def focusOutEvent(self, e):
        super().focusOutEvent(e); self._set_focus_prop(False)
    def _set_focus_prop(self, on):
        box = self.parentWidget()
        while box is not None and box.objectName() != 'ComposerBox': box = box.parentWidget()
        if box is not None:
            box.setProperty('focused', 'true' if on else 'false'); box.style().unpolish(box); box.style().polish(box)


class Toast(QFrame):
    """Non-modal notification shown at the bottom of the window. Errors stay longer and may offer an action."""
    def __init__(self, host, text, kind='info', action=None, palette=None, timeout=None):
        super().__init__(host); self.setObjectName('Toast'); self.setProperty('kind', kind)
        self.setLayoutDirection(layout_direction())
        p = palette or {}
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 10, 10, 10); layout.setSpacing(10)
        name = {'error': 'alert', 'success': 'check'}.get(kind, 'info')
        color = {'error': p.get('danger', '#dc2626'), 'success': p.get('success', '#059669')}.get(kind, p.get('accent', '#4f46e5'))
        badge = QLabel(); badge.setPixmap(icons.pixmap(name, color, 20)); badge.setFixedWidth(22); layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        self.label = QLabel(text); self.label.setObjectName('ToastText'); self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); self.label.setMinimumWidth(260)
        layout.addWidget(self.label, 1)
        self.action_button = None
        if action:
            title, callback = action
            self.action_button = QPushButton(title); self.action_button.setObjectName('Primary'); self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.action_button.clicked.connect(lambda: (callback(), self.dismiss())); layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignVCenter)
        close = QToolButton(); close.setIcon(icons.icon('close', p.get('muted', '#64748b'), 16)); close.setToolTip(tr('بستن')); close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.effect = QGraphicsOpacityEffect(self); self.setGraphicsEffect(self.effect); self.effect.setOpacity(0.0)
        self.fade = QPropertyAnimation(self.effect, b'opacity', self); self.fade.setDuration(180); self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.dismiss)
        self.timer.start(timeout if timeout is not None else (12000 if kind == 'error' else 3500))
        self.closed = False
    def show_animated(self):
        self.show(); self.raise_(); self.fade.stop(); self.fade.setStartValue(0.0); self.fade.setEndValue(1.0); self.fade.start()
    def dismiss(self):
        if self.closed: return
        self.closed = True; self.timer.stop()
        self.fade.stop(); self.fade.setStartValue(self.effect.opacity()); self.fade.setEndValue(0.0)
        self.fade.finished.connect(self._remove); self.fade.start()
    def _remove(self):
        host = self.parentWidget(); self.hide(); self.deleteLater()
        if host is not None and hasattr(host, '_toast_removed'): host._toast_removed(self)


class ToastHost:
    """Mixin for a widget that stacks toasts above its bottom edge."""
    def init_toasts(self, bottom_margin=110):
        self._toasts = []; self._toast_bottom = bottom_margin
    def toast(self, text, kind='info', action=None, timeout=None):
        t = Toast(self, text, kind, action, getattr(self, 'palette_values', None), timeout)
        self._toasts.append(t); self._layout_toasts(); t.show_animated()
        while len(self._toasts) > 3: self._toasts[0].dismiss(); self._toasts.pop(0)
        return t
    def _toast_removed(self, toast):
        if toast in self._toasts: self._toasts.remove(toast)
        self._layout_toasts()
    def _layout_toasts(self):
        width = min(560, max(320, self.width() - 80)); y = self.height() - self._toast_bottom
        for t in reversed(self._toasts):
            t.setFixedWidth(width); t.adjustSize(); y -= t.height() + 8
            t.move((self.width() - width) // 2, max(8, y))


class StatusIndicator(QWidget):
    """Coloured dot + text; pulses while streaming."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(6)
        self.dot = QLabel(); self.dot.setObjectName('StatusDot'); self.dot.setFixedSize(8, 8)
        self.text = QLabel(); self.text.setObjectName('Muted')
        layout.addWidget(self.dot); layout.addWidget(self.text)
        self.timer = QTimer(self); self.timer.setInterval(450); self.timer.timeout.connect(self._tick); self.phase = 0
        self.colors = {'idle': '#10b981', 'busy': '#6366f1', 'error': '#ef4444', 'muted': '#94a3b8'}; self.base = ''; self.state = 'idle'
    def set_palette(self, p):
        self.colors = {'idle': p['success'], 'busy': p['accent'], 'error': p['danger'], 'muted': p['muted']}; self._paint(True)
    def set_state(self, state, text):
        self.state = state; self.base = text; self.phase = 0
        if state == 'busy': self.timer.start()
        else: self.timer.stop()
        self.text.setText(text); self._paint(True)
    def _tick(self):
        self.phase = (self.phase + 1) % 4; self.text.setText(self.base + '.' * self.phase); self._paint(self.phase % 2 == 0)
    def _paint(self, strong):
        color = self.colors.get(self.state, '#94a3b8')
        self.dot.setStyleSheet(f'background:{color}; border-radius:4px;' + ('' if strong else 'background:transparent; border:2px solid ' + color + ';'))
