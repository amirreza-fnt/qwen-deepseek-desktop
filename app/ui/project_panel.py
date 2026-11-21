"""Project mode panel: project folder, file tree with attachable files, and the review of proposed changes
(diff view, apply / reject per file, apply all, undo last apply). Nothing is written without a click."""
from app.i18n import tr, layout_direction, label_alignment, ui_dir, ui_align
import html, os
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QCheckBox, QTabWidget, QWidget,
                               QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem, QTextBrowser, QMessageBox, QSplitter, QLineEdit)
from app.project import core
from app.ui import render, icons

KIND_LABEL = {'create': tr('ساخت'), 'modify': tr('ویرایش'), 'delete': tr('حذف'), 'mkdir': tr('ساخت پوشه')}
STATE_LABEL = {'pending': tr('در انتظار بررسی'), 'applied': tr('اعمال شد'), 'rejected': tr('رد شد'), 'error': tr('خطا')}
MAX_DIFF_LINES = 4000


def diff_html(change, p, side_by_side=False):
    """Syntax-highlighted, LTR diff of one change (unified or side by side)."""
    lexer = render.lexer_for('file:' + change.path)
    add_bg, del_bg, hunk = '#12351f', '#3d1518', '#1e293b'
    mono = render.MONO
    def hl(text):
        return render.highlight_lines(text, lexer) if text else '&nbsp;'
    head = (f'<p dir="ltr" align="left" style="{mono} color:{p["muted"]}; margin:0 0 6px 0;">{html.escape(change.path)} — '
            f'{KIND_LABEL.get(change.kind, change.kind)}</p>')
    if change.error:
        return head + f'<p dir="{ui_dir()}" style="color:{p["danger"]};">{html.escape(change.error)}</p>'
    note_html = ''.join(f'<p dir="{ui_dir()}" style="color:{p["muted"]};">{html.escape(n)}</p>' for n in change.notes)
    if change.kind == 'mkdir' or change.raw is not None:
        return head + note_html
    if change.kind == 'delete':
        return head + note_html + tr('<p dir="rtl" style="color:{v0};">این فایل حذف می‌شود ({v1} خط).</p>', v0=p["danger"], v1=len((change.old or "").splitlines()))
    lines = core.unified_diff(change)
    if not lines:
        return head + tr('<p dir="rtl">تغییری در محتوا نیست.</p>')
    cut = len(lines) > MAX_DIFF_LINES; lines = lines[:MAX_DIFF_LINES]
    rows = []
    if not side_by_side:
        for line in lines[2:]:
            if line.startswith('@@'): bg, sign, body = hunk, '', f'<span style="color:#93c5fd;">{html.escape(line)}</span>'
            elif line.startswith('+'): bg, sign, body = add_bg, '+', hl(line[1:])
            elif line.startswith('-'): bg, sign, body = del_bg, '−', hl(line[1:])
            else: bg, sign, body = p['code_bg'], ' ', hl(line[1:])
            rows.append(f'<p dir="ltr" align="left" style="background-color:{bg}; margin:0; white-space:pre; {mono} color:{p["code_text"]};">'
                        f'<span style="color:#64748b;">{sign}&nbsp;</span>{body}</p>')
    else:
        left = []; right = []
        def flush():
            n = max(len(left), len(right))
            for i in range(n):
                l = left[i] if i < len(left) else None; r = right[i] if i < len(right) else None
                rows.append('<tr>' + cell(l) + cell(r) + '</tr>')
            left.clear(); right.clear()
        def cell(item):
            if item is None: return f'<td width="50%" bgcolor="{p["code_bg"]}">&nbsp;</td>'
            kind, text = item; bg = {'+': add_bg, '-': del_bg}.get(kind, p['code_bg'])
            return f'<td width="50%" bgcolor="{bg}" style="{mono} color:{p["code_text"]}; white-space:pre;">{hl(text)}</td>'
        for line in lines[2:]:
            if line.startswith('@@'): flush(); rows.append(f'<tr><td colspan="2" bgcolor="{hunk}" style="{mono} color:#93c5fd;">{html.escape(line)}</td></tr>')
            elif line.startswith('-'): left.append(('-', line[1:]))
            elif line.startswith('+'): right.append(('+', line[1:]))
            else: flush(); left.append((' ', line[1:])); right.append((' ', line[1:])); flush()
        flush()
        rows = ['<table width="100%" cellspacing="0" cellpadding="2" dir="ltr">'] + rows + ['</table>']
    notes = ''.join(f'<p dir="{ui_dir()}" style="color:{p["muted"]};">{html.escape(n)}</p>' for n in change.notes)
    tail = tr('<p dir="rtl" style="color:{v0};">… diff کوتاه شد</p>', v0=p["muted"]) if cut else ''
    return head + notes + ''.join(rows) + tail


class ProjectPanel(QFrame):
    choose_folder = Signal()
    mode_toggled = Signal(bool)
    attached_changed = Signal(list)
    ask_fix = Signal(object)
    changes_applied = Signal(list)

    def __init__(self, palette, parent=None):
        super().__init__(parent); self.setObjectName('ProjectPanel'); self.p = palette
        self.root = None; self.files = []; self.truncated = False; self.changes = []; self.history_base = None; self.confirm = True
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 12, 10, 10); lay.setSpacing(8)
        top = QHBoxLayout(); title = QLabel(tr('پروژه')); title.setObjectName('ChatTitle'); top.addWidget(title); top.addStretch()
        self.pick = QPushButton(tr('انتخاب پوشه پروژه')); self.pick.setObjectName('Ghost'); top.addWidget(self.pick); lay.addLayout(top)
        self.folder = QLabel(tr('پوشه‌ای انتخاب نشده است')); self.folder.setObjectName('Muted'); self.folder.setWordWrap(True); lay.addWidget(self.folder)
        self.mode = QCheckBox(tr('حالت پروژه برای این گفت‌وگو')); self.mode.setToolTip(tr('مدل می‌تواند فایل بسازد یا ویرایش کند؛ هیچ تغییری بدون تأیید شما نوشته نمی‌شود')); lay.addWidget(self.mode)
        self.tools = QCheckBox(tr('ابزارهای عامل (خواندن، جست‌وجو، ترمینال، وب)'))
        self.tools.setToolTip(tr('مدل می‌تواند ساختار پوشه را ببیند، فایل پیدا کند و بخواند و تصویرها را بررسی کند (خودکار و فقط داخل پوشهٔ پروژه).\n'
                              'اجرای فرمان، دانلود و درخواست به نشانی‌های غیرمحلی فقط با زدن «اجرا» روی کارت آن انجام می‌شود.'))
        self.tools.setChecked(True); lay.addWidget(self.tools)
        self.allow_ro = QCheckBox(tr('اجرای خودکار فرمان‌های فقط‌خواندنی در این نشست'))
        self.allow_ro.setToolTip(tr('فقط فرمان‌هایی مثل dir، Get-Content، git status/log/diff یا node --version بدون تأیید اجرا می‌شوند؛\n'
                                 'هر فرمانی که چیزی را تغییر دهد همچنان تأیید می‌خواهد. با بستن برنامه خاموش می‌شود.'))
        self.allow_ro.setChecked(False); lay.addWidget(self.allow_ro)
        self.tools.toggled.connect(self.allow_ro.setEnabled)
        self.tabs = QTabWidget(); lay.addWidget(self.tabs, 1)
        # files tab
        files = QWidget(); fl = QVBoxLayout(files); fl.setContentsMargins(0, 6, 0, 0)
        self.filter = QLineEdit(); self.filter.setPlaceholderText(tr('فیلتر فایل‌ها')); self.filter.setClearButtonEnabled(True); fl.addWidget(self.filter)
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setLayoutDirection(Qt.LayoutDirection.LeftToRight); fl.addWidget(self.tree, 1)
        self.budget = QLabel(); self.budget.setObjectName('Muted'); self.budget.setWordWrap(True); fl.addWidget(self.budget)
        hint = QLabel(tr('فایل‌ها را تیک بزنید یا در پیام بنویسید @نام‌فایل تا محتوایشان فرستاده شود.')); hint.setObjectName('Muted'); hint.setWordWrap(True); fl.addWidget(hint)
        self.tabs.addTab(files, tr('فایل‌ها'))
        # changes tab
        review = QWidget(); rl = QVBoxLayout(review); rl.setContentsMargins(0, 6, 0, 0)
        self.progress = QLabel(''); self.progress.setObjectName('Muted'); self.progress.setWordWrap(True); rl.addWidget(self.progress)
        split = QSplitter(Qt.Orientation.Vertical)
        self.change_list = QListWidget(); self.change_list.setLayoutDirection(Qt.LayoutDirection.LeftToRight); split.addWidget(self.change_list)
        self.diff = QTextBrowser(); self.diff.setOpenLinks(False); self.diff.setLayoutDirection(Qt.LayoutDirection.LeftToRight); split.addWidget(self.diff)
        split.setSizes([120, 400]); rl.addWidget(split, 1)
        row = QHBoxLayout(); row.setSpacing(4)
        self.apply_one = QPushButton(tr('اعمال')); self.apply_one.setObjectName('Primary'); self.reject_one = QPushButton(tr('رد')); self.apply_all = QPushButton(tr('اعمال همه'))
        self.fix = QPushButton(tr('درخواست اصلاح از مدل')); self.side = QCheckBox(tr('کنار هم'))
        for w in (self.apply_one, self.reject_one, self.apply_all, self.fix): row.addWidget(w)
        row.addStretch(); row.addWidget(self.side); rl.addLayout(row)
        row2 = QHBoxLayout(); self.open_file = QPushButton(tr('باز کردن در ویرایشگر')); self.open_dir = QPushButton(tr('باز کردن پوشه'))
        row2.addWidget(self.open_file); row2.addWidget(self.open_dir); row2.addStretch(); rl.addLayout(row2)
        self.tabs.addTab(review, tr('تغییرات پیشنهادی'))
        bottom = QHBoxLayout(); self.undo = QPushButton(tr('بازگردانی آخرین تغییرات')); self.refresh_button = QPushButton(tr('بازخوانی'))
        bottom.addWidget(self.undo); bottom.addStretch(); bottom.addWidget(self.refresh_button); lay.addLayout(bottom)
        self.pick.clicked.connect(self.choose_folder); self.mode.toggled.connect(self.mode_toggled); self.refresh_button.clicked.connect(self.refresh)
        self.tree.itemChanged.connect(self._item_changed); self.filter.textChanged.connect(self._apply_filter)
        self.change_list.currentRowChanged.connect(self._show_change); self.side.toggled.connect(lambda _: self._show_change(self.change_list.currentRow()))
        self.apply_one.clicked.connect(lambda: self._apply([self.current()])); self.apply_all.clicked.connect(lambda: self._apply([c for c in self.changes if c.state == 'pending']))
        self.reject_one.clicked.connect(self._reject); self.fix.clicked.connect(lambda: self.current() and self.ask_fix.emit(self.current()))
        self.undo.clicked.connect(self._undo); self.open_file.clicked.connect(self._open_file); self.open_dir.clicked.connect(self._open_dir)
        self.set_project(None, False, []); self._update_buttons()

    # ----- project / tree ---------------------------------------------------------------------------------
    def set_project(self, root, mode, attached):
        self.root = root if root and os.path.isdir(root) else None
        self.mode.blockSignals(True); self.mode.setChecked(bool(mode and self.root)); self.mode.setEnabled(bool(self.root)); self.mode.blockSignals(False)
        self.folder.setText(root if self.root else (tr('پوشهٔ ذخیره‌شده پیدا نشد: ') + root if root else tr('پوشه‌ای انتخاب نشده است')))
        self.attached = set(attached or [])
        self.refresh()

    def refresh(self):
        self.tree.blockSignals(True); self.tree.clear(); self.files = []
        if self.root:
            self.files, self.truncated = core.scan(self.root)
            dirs = {}
            for rel, size in self.files:
                parts = rel.split('/'); parent = self.tree.invisibleRootItem(); path = ''
                for part in parts[:-1]:
                    path = f'{path}/{part}' if path else part
                    if path not in dirs:
                        item = QTreeWidgetItem([part + '/']); parent.addChild(item); dirs[path] = item
                    parent = dirs[path]
                item = QTreeWidgetItem([f'{parts[-1]}  ({size // 1024 if size >= 1024 else size}{"KB" if size >= 1024 else "B"})'])
                item.setData(0, Qt.ItemDataRole.UserRole, rel); item.setToolTip(0, rel)
                if size <= core.MAX_FILE_BYTES:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Checked if rel in self.attached else Qt.CheckState.Unchecked)
                else:
                    item.setToolTip(0, rel + tr(' — بزرگ‌تر از حد پیوست'))
                parent.addChild(item)
            if len(self.files) < 300: self.tree.expandAll()
        self.attached = {a for a in self.attached if a in dict(self.files)}
        self.tree.blockSignals(False); self._update_budget(); self._apply_filter(self.filter.text())

    def _item_changed(self, item, _col):
        rel = item.data(0, Qt.ItemDataRole.UserRole)
        if not rel: return
        if item.checkState(0) == Qt.CheckState.Checked: self.attached.add(rel)
        else: self.attached.discard(rel)
        self._update_budget(); self.attached_changed.emit(sorted(self.attached))

    def set_attached(self, rels):
        self.attached |= {r for r in rels if r in dict(self.files)}
        self.refresh(); self.attached_changed.emit(sorted(self.attached))

    def _apply_filter(self, text):
        text = (text or '').strip().lower()
        def visit(item):
            rel = item.data(0, Qt.ItemDataRole.UserRole)
            if rel: show = not text or text in rel.lower()
            else: show = any([visit(item.child(i)) for i in range(item.childCount())])
            item.setHidden(not show); return show
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()): visit(root.child(i))

    def context_chars(self):
        return core.context_size(self.root, sorted(self.attached), self.files) if self.root else 0

    def _update_budget(self):
        if not self.root: self.budget.setText(''); return
        chars = self.context_chars(); budget = core.CONTEXT_BUDGET_CHARS
        warn = chars > budget
        self.budget.setText(tr('{n} فایل{cut} · پیوست: {att} فایل · حجم زمینه ≈ {chars:,} نویسه (~{tokens:,} توکن) از {budget:,}', n=len(self.files), cut=tr(' (فهرست کوتاه شد)') if self.truncated else '', att=len(self.attached), chars=chars, tokens=chars // 4, budget=budget) + (tr(' — بیش از حد! چند فایل را بردارید.') if warn else ''))
        self.budget.setStyleSheet(f'color:{self.p["danger"]};' if warn else '')

    # ----- review -----------------------------------------------------------------------------------------
    def set_progress(self, text):
        self.progress.setText(text)

    def set_changes(self, changes):
        self.changes = list(changes); self.change_list.clear()
        for ch in self.changes:
            self.change_list.addItem(QListWidgetItem(self._label(ch)))
        self.tabs.setTabText(1, tr('تغییرات پیشنهادی ({v0})', v0=len(self.changes)) if self.changes else tr('تغییرات پیشنهادی'))
        if self.changes: self.change_list.setCurrentRow(0); self.tabs.setCurrentIndex(1)
        else: self.diff.clear()
        self._update_buttons()

    def _label(self, ch):
        mark = {'create': '✚', 'modify': '✎', 'delete': '✖', 'mkdir': '📁'}.get(ch.kind, '•') if not ch.error else '⚠'
        stats = ''
        if not ch.error and ch.kind not in ('delete', 'mkdir') and ch.raw is None:
            plus, minus = core.diff_stats(ch); stats = f'  +{plus} −{minus}'
        return f'{mark} {ch.path}{stats}  — {STATE_LABEL[ch.state]}'

    def current(self):
        row = self.change_list.currentRow()
        return self.changes[row] if 0 <= row < len(self.changes) else None

    def _show_change(self, row):
        ch = self.changes[row] if 0 <= row < len(self.changes) else None
        self.diff.setHtml(diff_html(ch, self.p, self.side.isChecked()) if ch else ''); self._update_buttons()

    def _refresh_labels(self):
        for i, ch in enumerate(self.changes): self.change_list.item(i).setText(self._label(ch))
        self._update_buttons()

    def _update_buttons(self):
        ch = self.current()
        self.apply_one.setEnabled(bool(ch and ch.state == 'pending' and self.root))
        self.reject_one.setEnabled(bool(ch and ch.state == 'pending'))
        self.apply_all.setEnabled(any(c.state == 'pending' for c in self.changes) and bool(self.root))
        self.fix.setEnabled(bool(ch and ch.state == 'error'))
        self.open_file.setEnabled(bool(ch and ch.state == 'applied' and ch.kind != 'delete'))
        self.open_dir.setEnabled(bool(self.root))
        self.undo.setEnabled(bool(self.root and core.history_entries(self.root, self.history_base)))

    def _ask(self, title, text):
        if not self.confirm: return True
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _apply(self, changes):
        changes = [c for c in changes if c is not None and c.state == 'pending']
        if not changes or not self.root: return
        deletes = [c.path for c in changes if c.kind == 'delete']
        if deletes and not self._ask(tr('تأیید حذف'), tr('این فایل‌ها حذف می‌شوند (نسخهٔ پشتیبان نگه داشته می‌شود):\n\n') + '\n'.join(deletes)):
            return
        try:
            core.apply_changes(self.root, changes, self.history_base)
        except (core.PathError, OSError, UnicodeError) as e:
            QMessageBox.warning(self, tr('اعمال نشد'), tr('هیچ فایلی تغییر نکرد:\n{e}', e=e)) if self.confirm else None
            self.last_error = str(e); return
        self._refresh_labels(); self.refresh(); self.changes_applied.emit([c.path for c in changes])

    def _reject(self):
        ch = self.current()
        if ch and ch.state == 'pending': ch.state = 'rejected'; self._refresh_labels()

    def _undo(self):
        if not self.root: return
        if not self._ask(tr('بازگردانی'), tr('آخرین تغییرات اعمال‌شده بازگردانده شود؟')): return
        restored = core.undo_last(self.root, self.history_base)
        for ch in self.changes:
            if ch.path in restored and ch.state == 'applied': ch.state = 'pending'
        self._refresh_labels(); self.refresh(); self._show_change(self.change_list.currentRow())
        self.last_undo = restored

    def _open_file(self):
        ch = self.current()
        if ch and self.root:
            try: QDesktopServices.openUrl(QUrl.fromLocalFile(str(core.safe_path(self.root, ch.path))))
            except core.PathError: pass

    def _open_dir(self):
        if self.root: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root))
