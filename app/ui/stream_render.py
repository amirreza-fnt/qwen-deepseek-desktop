"""Incremental Markdown rendering of a reply while it streams.

Text arriving from the network is committed in place inside the streaming bubble of the QTextBrowser:
complete paragraphs are rendered as Markdown once, an open ``` fence becomes a real code block (LTR,
monospaced, highlighted, with a copy link) and every complete code line is appended to it as it arrives.
Only the unfinished tail (the current paragraph or the current partial code line) is re-rendered on each
update, so the cost per update is proportional to the new text, not to the whole reply. When the stream
ends the window re-renders the message from the database with ``render.message_html`` (same styles).
"""
import html
import re
from PySide6.QtGui import QTextCursor, QTextBlockFormat, QTextCharFormat, QTextDocument, QTextDocumentFragment
from app.ui import render

CONTEXT_LINES = 40
CODE_MARK = '\u2064'  # invisible plus: temporary anchor inside the streaming code cell


class StreamRenderer:
    def __init__(self, document, cursor, palette):
        self.doc = document; self.cursor = QTextCursor(cursor); self.p = palette
        if self.cursor.hasSelection():
            if self.cursor.selectedText() == render.STREAM_MARK: self.cursor.removeSelectedText()
            self.cursor.clearSelection()
        probe = QTextCursor(self.cursor); probe.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if probe.selectedText() == render.STREAM_MARK: probe.removeSelectedText()  # the paragraph is ours now
        self.buf = ''; self.pos = 0; self.mode = 'prose'
        self.code_cursor = None; self.lang = ''; self.lexer = None
        self.blocks = []        # code text of each streaming block / inline span (for copy-stream:N links)
        self.code_index = None
        self.tail = None        # (QTextCursor, start, end) of the uncommitted tail
        self.need_block = False # a code line ended: the next code text starts a new paragraph (block)

    # ----- helpers ---------------------------------------------------------
    def _remove_tail(self):
        if self.tail is None: return
        cur, start, end = self.tail; self.tail = None
        c = QTextCursor(self.doc); c.setPosition(start); c.setPosition(end, QTextCursor.MoveMode.KeepAnchor); c.removeSelectedText()

    def _insert(self, cur, fragment):
        """insertHtml, but keep the first paragraph's own format (dir, background, margins): Qt merges the
        first inserted paragraph into the (empty) paragraph at the cursor and would drop its block format."""
        if not fragment: return
        frag = QTextDocumentFragment.fromHtml(fragment, self.doc)
        scratch = QTextDocument(); scratch.setDefaultStyleSheet(self.doc.defaultStyleSheet()); scratch.setHtml(fragment)
        first = scratch.begin().blockFormat()
        start = cur.position(); empty = cur.block().length() <= 1
        cur.insertFragment(frag)
        if empty:
            block = self.doc.findBlock(start)
            if block.length() <= 1 and block.next().isValid():
                # Qt inserted the fragment (e.g. a list) after the empty paragraph instead of merging: drop it
                drop = QTextCursor(self.doc); drop.setPosition(start); drop.setPosition(start + 1, QTextCursor.MoveMode.KeepAnchor); drop.removeSelectedText()
            else:
                QTextCursor(block).setBlockFormat(first)

    def _commit(self, fragment):
        """Insert finished HTML and start a fresh, plain paragraph for whatever comes next."""
        if not fragment: return
        self._insert(self.cursor, fragment)
        self.cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())

    def _prose_html(self, text):
        return render._prose(text, self.blocks, self.p, 'copy-stream')

    def _open_code(self, lang):
        self.lang = lang; self.lexer = render.lexer_for(lang)
        name = (lang or '').strip().lower().split()[0] if (lang or '').strip() else ''
        self.html_like = name in ('html', 'htm', 'xhtml', 'vue', 'svelte', 'php', 'jinja', 'django')
        self.sub_lexers = {'style': render.lexer_for('css'), 'script': render.lexer_for('javascript')} if self.html_like else {}
        self.code_index = len(self.blocks); self.blocks.append('')
        start = self.cursor.position()
        self._commit(render.code_block_html(lang, self.code_index, self.p, CODE_MARK, 'copy-stream'))
        found = self.doc.find(CODE_MARK, start)
        if found.isNull(): found = self.doc.find(CODE_MARK)
        if found.isNull():
            self.code_cursor = QTextCursor(self.cursor)
        else:
            found.removeSelectedText(); self.code_cursor = QTextCursor(found)
        self.mode = 'code'

    def _code_span(self, body):
        return f'<span style="{render.MONO} color:{self.p["code_text"]};">{body}</span>'

    _EMBED = re.compile(r'<(/?)(style|script)\b', re.I)

    def _highlight(self, code):
        """Highlight newly completed lines with some preceding lines as context, so multi-line constructs keep
        their colours; for HTML, lines inside <style>/<script> are lexed as CSS/JavaScript. Cost stays
        proportional to the new text (the context is bounded)."""
        lexer = self.lexer; done = self.blocks[self.code_index][:-len(code)] if code else ''
        if self.html_like:
            m = None
            for m in self._EMBED.finditer(done): pass
            inside = m and not m.group(1) and '>' in done[m.end():]
            if inside:
                lexer = self.sub_lexers.get(m.group(2).lower(), lexer)
                start = done.rfind('>', m.end()) + 1   # context starts right after the <style ...> tag
                done = done[max(start, len(done) - 2000):]
        context = '\n'.join(done.split('\n')[-CONTEXT_LINES:]) if done else ''
        if context and not context.endswith('\n'): context = context[:context.rfind('\n') + 1] if '\n' in context else ''
        if not context: return render.highlight_lines(code, lexer)
        out = render.highlight_lines(context + code, lexer)
        skip = context.count('\n')
        parts = out.split('<br/>')
        return '<br/>'.join(parts[skip:])

    def _new_code_line(self, cur):
        # Every code line is its own paragraph: Qt lays out per block, so appending stays O(new text)
        # (one huge <br/>-separated paragraph would be re-laid out completely on every insertion).
        if self.need_block: cur.insertBlock(); cur.insertText(render.CODE_PAD); self.need_block = False

    def _append_code(self, code):
        """Append complete code text (lines ending in '\n', or the last line before the closing fence)."""
        if not code: return
        if self.html_like and self._EMBED.search(code):
            # lines with <style>/<script>/</style>/</script> are handled on their own so the lines after them are
            # lexed with the right (CSS/JavaScript/HTML) lexer
            lines = code.splitlines(True); run = []
            for line in lines:
                if self._EMBED.search(line):
                    if run: self._append_piece(''.join(run)); run = []
                    self._append_piece(line)
                else: run.append(line)
            if run: self._append_piece(''.join(run))
        else:
            self._append_piece(code)

    def _append_piece(self, code):
        self.blocks[self.code_index] += code
        body = self._highlight(code).replace('<br/>', '\n')
        lines = body.split('\n')
        if code.endswith('\n'): lines = lines[:-1]
        for i, line in enumerate(lines):
            self._new_code_line(self.code_cursor)
            if line: self.code_cursor.insertHtml(self._code_span(line))
            if i < len(lines) - 1 or code.endswith('\n'): self.need_block = True

    # ----- public API --------------------------------------------------------
    def feed(self, text):
        """Add streamed text and update the document (call from the GUI thread, throttled)."""
        self.buf += text
        self._remove_tail()
        while True:
            if self.mode == 'prose':
                opened = render.FENCE_OPEN.search(self.buf, self.pos)
                if opened:
                    self._commit(self._prose_html(self.buf[self.pos:opened.start()]))
                    self.pos = opened.end(); self.close_re = render.fence_close(opened.group('fence')); self._open_code(opened.group('lang')); continue
                cut = self.buf.rfind('\n\n', self.pos)
                if cut >= 0:
                    self._commit(self._prose_html(self.buf[self.pos:cut + 2])); self.pos = cut + 2
                tail = self.buf[self.pos:]
                if tail.strip():
                    cur = self.cursor; start = cur.position(); self._insert(cur, self._prose_html(tail)); self.tail = (cur, start, cur.position())
                break
            closed = (getattr(self, 'close_re', None) or render.FENCE_CLOSE).search(self.buf, self.pos)
            if closed and closed.group(0).endswith('\n'):
                self._append_code(self.buf[self.pos:closed.start()].rstrip('\n'))
                self.pos = closed.end(); self.mode = 'prose'; self.code_cursor = None; self.need_block = False; continue
            nl = self.buf.rfind('\n', self.pos)
            if nl >= 0:
                self._append_code(self.buf[self.pos:nl + 1]); self.pos = nl + 1
            tail = self.buf[self.pos:]
            if tail:
                cur = self.code_cursor; start = cur.position(); need = self.need_block
                self._new_code_line(cur)
                cur.insertHtml(self._code_span(html.escape(tail).replace("  ", "&nbsp; ")))  # inline only
                self.tail = (cur, start, cur.position()); self.need_block = need
            break

    def code_for_link(self, index):
        return self.blocks[index] if 0 <= index < len(self.blocks) else None
