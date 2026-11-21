"""Structured, language-agnostic edit tools for the project agent.

Instead of retyping code, the model refers to locations (file + line range, optionally checked by text markers) and
the app does the mechanical work: move/copy/delete/replace lines, insert text or a whole file, literal/regex
search-replace over one file or a glob, rename/move/copy paths (with best-effort import/require/include updates),
make folders, and apply unified diffs.

Nothing here writes to disk. Every call edits an in-memory ``EditSession``; ``session.changes()`` returns
``core.Change`` objects for the existing review panel (diff → «اعمال» → backup → atomic write → undo).
Paths are sandboxed with ``core.safe_path``. Text keeps its encoding/BOM/line endings (``core.TextInfo``).
"""
from app.i18n import tr
import os, posixpath, re
from pathlib import Path
from app.project import core

EDIT_TOOLS = {
    'move_lines': ('from', {'from', 'start', 'end', 'start_marker', 'end_marker', 'to', 'position', 'to_line', 'after', 'before', 'indent'}),
    'copy_lines': ('from', {'from', 'start', 'end', 'start_marker', 'end_marker', 'to', 'position', 'to_line', 'after', 'before', 'indent'}),
    'delete_lines': ('path', {'path', 'start', 'end', 'start_marker', 'end_marker'}),
    'replace_lines': ('path', {'path', 'start', 'end', 'start_marker', 'end_marker', 'text', 'indent'}),
    'insert_text': ('path', {'path', 'text', 'position', 'to_line', 'after', 'before', 'indent'}),
    'insert_file_content': ('from', {'from', 'to', 'position', 'to_line', 'after', 'before', 'indent'}),
    'replace_text': ('pattern', {'pattern', 'replacement', 'path', 'glob', 'regex', 'case_sensitive', 'expected_count', 'max_count', 'dry_run'}),
    'move_path': ('from', {'from', 'to', 'update_references', 'overwrite'}),
    'rename_path': ('from', {'from', 'to', 'update_references', 'overwrite'}),
    'copy_path': ('from', {'from', 'to', 'overwrite'}),
    'make_dir': ('path', {'path'}),
    'apply_patch': ('patch', {'patch'}),
}
MAX_PATH_FILES = 1000
MAX_PATH_BYTES = 50 * 1024 * 1024
MAX_REPLACE_FILES = 300
REF_MAX_BYTES = 1_000_000


class EditError(ValueError):
    pass


# ----- line helpers (text is '\n'-normalised by core.read_text) ------------------------------------------------------------
def split_lines(text):
    """Lines including their '\n' (the last one may lack it)."""
    return re.findall(r'[^\n]*\n|[^\n]+$', text or '')


def _indent_of(line):
    return line[:len(line) - len(line.lstrip(' \t'))]


def adjust_indent(lines, indent, context_line=None):
    """indent: int (+add / -remove spaces), a string to use as the new base indentation, or 'auto' (match context_line)."""
    if indent in (None, 0, '', False): return lines
    body = [l for l in lines if l.strip()]
    if not body: return lines
    base = min((_indent_of(l) for l in body), key=len)
    if indent == 'auto':
        if context_line is None: return lines
        target = _indent_of(context_line)
    elif isinstance(indent, str):
        target = indent
    else:
        try: n = int(indent)
        except (TypeError, ValueError): raise EditError(tr('indent باید عدد، "auto" یا رشتهٔ فاصله باشد'))
        if n > 0: return [(' ' * n + l) if l.strip() else l for l in lines]
        out = []
        for l in lines:
            k = 0
            while k < -n and k < len(l) and l[k] in ' \t': k += 1
            out.append(l[k:])
        return out
    return [(target + l[len(base):]) if l.strip() and l.startswith(base) else l for l in lines]


def _unique_line(lines, marker, label, start=0):
    hits = [i for i in range(start, len(lines)) if marker in lines[i]]
    if not hits: raise EditError(tr('{label} «{marker}» پیدا نشد', label=label, marker=marker))
    if len(hits) > 1: raise EditError(tr('{label} «{marker}» در {v0} خط پیدا شد (خطوط {v1})؛ مبهم است', label=label, marker=marker, v0=len(hits), v1=", ".join(str(h + 1) for h in hits[:8])))
    return hits[0]


def resolve_range(lines, args, rel):
    """0-based [s, e) for the line range in args (start/end 1-based inclusive) checked/located by start_marker/end_marker."""
    start, end = args.get('start'), args.get('end')
    sm, em = args.get('start_marker'), args.get('end_marker')
    n = len(lines)
    try:
        start = int(start) if start not in (None, '') else None; end = int(end) if end not in (None, '') else None
    except (TypeError, ValueError): raise EditError(tr('start/end باید شمارهٔ خط باشند'))
    if start is None and not sm: raise EditError(tr('start (شمارهٔ خط) یا start_marker لازم است'))
    note = ''
    if start is not None:
        if end is None: end = start
        if not (1 <= start <= end <= n): raise EditError(tr('بازهٔ خطوط {start}-{end} در {rel} نامعتبر است (فایل {n} خط دارد)', start=start, end=end, rel=rel, n=n))
        s, e = start - 1, end
        if sm and sm not in lines[s]:
            ns = _unique_line(lines, sm, 'start_marker')           # numbers are stale: relocate both by the same delta
            delta = ns - s; s, e = ns, e + delta
            if e > n: raise EditError(tr('بازه پس از جابه‌جایی با start_marker از فایل بیرون می‌زند'))
            note = tr('شمارهٔ خطوط با start_marker {delta:+d} جابه‌جا شد', delta=delta)
        if em and em not in lines[e - 1]:
            raise EditError(tr('خط {e} در {rel} شامل end_marker «{em}» نیست؛ ابتدا read_file بگیرید', e=e, rel=rel, em=em))
    else:
        s = _unique_line(lines, sm, 'start_marker')
        if em:
            hits = [i for i in range(s, n) if em in lines[i]]
            if not hits: raise EditError(tr('end_marker «{em}» بعد از start_marker پیدا نشد', em=em))
            e = hits[0] + 1
        else: e = s + 1
    return s, e, note


def resolve_position(lines, args, default='end'):
    """0-based insertion index from position ('start'|'end') / to_line (insert before line N) / after / before (unique marker)."""
    keys = [k for k in ('to_line', 'after', 'before') if args.get(k) not in (None, '')]
    if len(keys) > 1: raise EditError(tr('فقط یکی از to_line / after / before را بدهید'))
    if keys == ['to_line']:
        try: n = int(args['to_line'])
        except (TypeError, ValueError): raise EditError(tr('to_line باید عدد باشد'))
        if not (1 <= n <= len(lines) + 1): raise EditError(tr('to_line={n} نامعتبر است (فایل {v0} خط دارد)', n=n, v0=len(lines)))
        return n - 1
    if keys == ['after']: return _unique_line(lines, str(args['after']), 'after') + 1
    if keys == ['before']: return _unique_line(lines, str(args['before']), 'before')
    pos = str(args.get('position') or default).lower()
    if pos in ('start', 'top', 'begin', 'beginning'): return 0
    if pos in ('end', 'bottom'): return len(lines)
    raise EditError(tr('position نامعتبر: {pos} (start یا end)', pos=pos))


def _ensure_nl(lines):
    if lines and not lines[-1].endswith('\n'): lines = lines[:-1] + [lines[-1] + '\n']
    return lines


def insert_lines(lines, index, block, indent=None):
    lines = list(lines)
    if index == len(lines): lines = _ensure_nl(lines)
    context = lines[index] if index < len(lines) and lines[index].strip() else next((l for l in reversed(lines[:index]) if l.strip()), None)
    block = adjust_indent(_ensure_nl(list(block)), indent, context)
    return lines[:index] + block + lines[index:]


# ----- session ---------------------------------------------------------------------------------------------------------------
class _File:
    def __init__(self):
        self.old = None        # text on disk (None: missing or binary)
        self.new = None        # proposed text (None: deleted / not text)
        self.info = None       # encoding / BOM / newline of the file
        self.raw = None        # proposed binary content (copy/move of a non-text file)
        self.exists = False    # exists on disk
        self.binary = False    # exists on disk but is not UTF-8 text
        self.deleted = False
        self.prune = False
        self.is_dir = False
        self.notes = []


class EditSession:
    """In-memory view of the project with pending edits (optionally seeded with earlier pending changes)."""

    def __init__(self, root, base_changes=()):
        self.root = str(Path(root).resolve()); self.files = {}; self.order = []
        for ch in base_changes:
            if ch.state != 'pending' or ch.error: continue
            f = self._entry(ch.path, load=False); f.notes = list(ch.notes)
            if ch.kind == 'mkdir': f.is_dir = True; continue
            f.old = ch.old; f.info = ch.info; f.raw = ch.raw; f.prune = ch.prune
            f.exists = ch.kind in ('modify', 'delete'); f.binary = ch.kind == 'delete' and not ch.old
            f.deleted = ch.kind == 'delete'; f.new = ch.new if ch.kind != 'delete' else None

    def _entry(self, rel, load=True):
        rel = core.clean_rel(rel)
        if rel in self.files: return self.files[rel]
        f = _File(); self.files[rel] = f; self.order.append(rel)
        if load:
            path = core.safe_path(self.root, rel)
            if path.is_dir(): f.is_dir = True; f.exists = True
            elif path.exists():
                f.exists = True
                try: f.info = core.read_text(path); f.old = f.info.text; f.new = f.old
                except UnicodeError: f.binary = True
        return f

    def exists(self, rel):
        rel = core.clean_rel(rel)
        if rel not in self.files: return core.safe_path(self.root, rel).exists()
        f = self.files[rel]
        if f.is_dir: return True
        if f.deleted: return f.raw is not None or f.new is not None
        return f.new is not None or f.raw is not None or f.binary

    def is_dir(self, rel):
        rel = core.clean_rel(rel)
        if rel in self.files: return self.files[rel].is_dir
        return core.safe_path(self.root, rel).is_dir()

    def text(self, rel):
        f = self._entry(rel)
        if f.is_dir: raise EditError(tr('{rel} یک پوشه است', rel=rel))
        if f.raw is not None or (f.binary and not f.deleted): raise EditError(tr('{rel} فایل متنی UTF-8 نیست', rel=rel))
        if f.new is None: raise EditError(tr('فایل وجود ندارد: {rel}', rel=rel))
        return f.new

    def info(self, rel):
        return self._entry(rel).info or core.TextInfo('', False, '\n')

    def set_text(self, rel, text, info=None, note=''):
        f = self._entry(rel)
        if f.is_dir: raise EditError(tr('{rel} یک پوشه است', rel=rel))
        if f.binary and not f.deleted: raise EditError(tr('{rel} فایل متنی UTF-8 نیست', rel=rel))
        if f.info is None or (f.old is None and info is not None): f.info = info or core.TextInfo('', False, '\n')
        f.new = text; f.raw = None; f.deleted = False
        if note and note not in f.notes: f.notes.append(note)

    def set_raw(self, rel, data, note=''):
        f = self._entry(rel)
        if f.is_dir: raise EditError(tr('{rel} یک پوشه است', rel=rel))
        if f.exists and not f.deleted: raise EditError(tr('{rel} از قبل وجود دارد؛ بازنویسی با فایل باینری پشتیبانی نمی‌شود', rel=rel))
        f.raw = data; f.new = None; f.deleted = False
        if note and note not in f.notes: f.notes.append(note)

    def delete(self, rel, prune=False, note=''):
        f = self._entry(rel)
        if f.is_dir: raise EditError(tr('{rel} یک پوشه است', rel=rel))
        if not self.exists(rel): raise EditError(tr('فایل وجود ندارد: {rel}', rel=rel))
        f.new = None; f.raw = None; f.deleted = True; f.prune = prune
        if note and note not in f.notes: f.notes.append(note)

    def mkdir(self, rel):
        rel = core.clean_rel(rel)
        if self.exists(rel):
            if self.is_dir(rel): return False
            raise EditError(tr('{rel} یک فایل است', rel=rel))
        f = self._entry(rel, load=False); f.is_dir = True
        return True

    def disk_files(self, base=''):
        """Files under ``base`` (all files except .git; symlinks skipped), merged with session creations/deletions."""
        root = Path(self.root); start = core.safe_path(self.root, base) if base else root; out = set()
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = [d for d in dirnames if d != '.git' and not os.path.islink(os.path.join(dirpath, d))]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if not os.path.islink(full): out.add(os.path.relpath(full, root).replace('\\', '/'))
        prefix = base + '/' if base else ''
        out.update(rel for rel in self.files if rel.startswith(prefix))
        return sorted(r for r in out if self.exists(r) and not self.is_dir(r))

    def read_bytes(self, rel):
        f = self._entry(rel)
        if f.raw is not None: return f.raw
        if f.new is not None: return core.encode_text(f.new, f.info or core.TextInfo(''))
        return core.safe_path(self.root, rel).read_bytes()

    def snapshot(self):
        return {rel: dict(vars(f), notes=list(f.notes)) for rel, f in self.files.items()}, list(self.order)

    def restore(self, snap):
        state, order = snap; self.order = order
        for rel in list(self.files):
            if rel not in state: del self.files[rel]
        for rel, values in state.items(): vars(self.files[rel]).update(values)

    def changes(self):
        out = []
        for rel in self.order:
            f = self.files[rel]
            if f.is_dir:
                if not f.exists: out.append(core.Change(rel, 'mkdir', None, None, None, notes=list(f.notes) or [tr('پوشهٔ تازه')]))
                continue
            if f.raw is not None:
                out.append(core.Change(rel, 'create', None, '', core.TextInfo(''), notes=list(f.notes) + [tr('فایل باینری ({v0:,} بایت)', v0=len(f.raw))], raw=f.raw))
            elif f.deleted:
                if f.exists: out.append(core.Change(rel, 'delete', f.old if f.old is not None else '', None, f.info or core.TextInfo(''), notes=list(f.notes), prune=f.prune))
            elif f.new is not None and f.new != f.old:
                out.append(core.Change(rel, 'create' if f.old is None else 'modify', f.old, f.new, f.info or core.TextInfo(''), notes=list(f.notes)))
        return out


# ----- the tools ------------------------------------------------------------------------------------------------------------
def _span(rel, s, e):
    return f'{rel}:{s + 1}-{e}' if e - s > 1 else f'{rel}:{s + 1}'


def _place(args):
    for k in ('to_line', 'after', 'before'):
        if args.get(k) not in (None, ''): return f'{k}={args[k]!r}' if k != 'to_line' else f'before line {args[k]}'
    return str(args.get('position') or 'end')


def t_lines(sess, args, move):
    src = core.clean_rel(str(args.get('from') or '')); dst = core.clean_rel(str(args.get('to') or src))
    lines = split_lines(sess.text(src)); s, e, note = resolve_range(lines, args, src)
    block = lines[s:e]
    if src == dst:
        index = resolve_position(lines, args)
        if move:
            if s < index < e: raise EditError(tr('مقصد داخل همان بازه‌ای است که جابه‌جا می‌شود'))
            rest = lines[:s] + lines[e:]
            if index >= e: index -= (e - s)
            new = insert_lines(rest, index, block, args.get('indent'))
        else:
            new = insert_lines(lines, index, block, args.get('indent'))
        sess.set_text(src, ''.join(new), note=tr('{what} خطوط {a}-{b} درون فایل', what=tr('جابه‌جایی') if move else tr('کپی'), a=s + 1, b=e))
    else:
        created = not sess.exists(dst)
        dlines = [] if created else split_lines(sess.text(dst))
        index = resolve_position(dlines, args)
        sess.set_text(dst, ''.join(insert_lines(dlines, index, block, args.get('indent'))), info=sess.info(src) if created else None,
                      note=tr('{v0} خط از {v1}', v0=e - s, v1=_span(src, s, e)) + (tr(' (فایل تازه)') if created else ''))
        if move: sess.set_text(src, ''.join(lines[:s] + lines[e:]), note=tr('{v0} خط به {dst} منتقل شد', v0=e - s, dst=dst))
    verb = 'moved' if move else 'copied'
    return f'{verb} {e - s} lines {_span(src, s, e)} -> {dst} ({_place(args)})' + (f'; {note}' if note else '')


def t_delete_lines(sess, args):
    rel = core.clean_rel(str(args.get('path') or '')); lines = split_lines(sess.text(rel)); s, e, note = resolve_range(lines, args, rel)
    sess.set_text(rel, ''.join(lines[:s] + lines[e:]), note=tr('حذف خطوط {v0}-{e}', v0=s + 1, e=e))
    return f'deleted {e - s} lines {_span(rel, s, e)}' + (f'; {note}' if note else '')


def t_replace_lines(sess, args):
    rel = core.clean_rel(str(args.get('path') or '')); lines = split_lines(sess.text(rel)); s, e, note = resolve_range(lines, args, rel)
    text = str(args.get('text') if args.get('text') is not None else '')
    new_block = split_lines(text if text.endswith('\n') or not text else text + '\n')
    if args.get('indent') is not None: new_block = adjust_indent(new_block, args.get('indent'), lines[s])
    if e == len(lines) and not lines[-1].endswith('\n') and new_block: new_block[-1] = new_block[-1].rstrip('\n')
    sess.set_text(rel, ''.join(lines[:s] + new_block + lines[e:]), note=tr('جایگزینی خطوط {v0}-{e}', v0=s + 1, e=e))
    return f'replaced lines {_span(rel, s, e)} with {len(new_block)} lines' + (f'; {note}' if note else '')


def t_insert_text(sess, args):
    rel = core.clean_rel(str(args.get('path') or '')); text = str(args.get('text') or '')
    if not text: raise EditError(tr('text خالی است'))
    created = not sess.exists(rel); lines = [] if created else split_lines(sess.text(rel)); index = resolve_position(lines, args)
    sess.set_text(rel, ''.join(insert_lines(lines, index, split_lines(text), args.get('indent'))), note=tr('درج متن') + (tr(' (فایل تازه)') if created else ''))
    return f'inserted {len(split_lines(text))} lines into {rel} ({_place(args)})'


def t_insert_file(sess, args):
    src = core.clean_rel(str(args.get('from') or '')); dst = core.clean_rel(str(args.get('to') or ''))
    block = split_lines(sess.text(src)); created = not sess.exists(dst)
    lines = [] if created else split_lines(sess.text(dst)); index = resolve_position(lines, args)
    sess.set_text(dst, ''.join(insert_lines(lines, index, block, args.get('indent'))), info=sess.info(src) if created else None,
                  note=tr('محتوای {src} درج شد', src=src))
    return f'inserted the content of {src} ({len(block)} lines) into {dst} ({_place(args)})'


def _replacement(rep, regex):
    rep = '' if rep is None else str(rep)
    return re.sub(r'\$(\d+)', r'\\g<\1>', rep) if regex else rep


def t_replace_text(sess, args, walk_files):
    pattern = str(args.get('pattern') or '')
    if not pattern: raise EditError(tr('pattern خالی است'))
    regex = bool(args.get('regex')); flags = (0 if args.get('case_sensitive', True) else re.I) | re.M
    try: rx = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e: raise EditError(tr('regex نامعتبر: {e}', e=e))
    rep = _replacement(args.get('replacement'), regex)
    if args.get('path'): files = [core.clean_rel(str(args['path']))]
    elif args.get('glob'): files = walk_files(str(args['glob']))
    else: raise EditError(tr('path یا glob لازم است'))
    counts = {}; new_texts = {}
    for rel in files:
        try: text = sess.text(rel)
        except EditError:
            if args.get('path'): raise
            continue
        try: new, n = rx.subn(rep if regex else (lambda m: rep), text)
        except (re.error, IndexError) as e: raise EditError(tr('replacement نامعتبر: {e}', e=e))
        if n: counts[rel] = n; new_texts[rel] = new
        if len(counts) > MAX_REPLACE_FILES: raise EditError(tr('بیش از {MAX_REPLACE_FILES} فایل تغییر می‌کند؛ glob را محدودتر کنید', MAX_REPLACE_FILES=MAX_REPLACE_FILES))
    total = sum(counts.values())
    report = f'{total} matches in {len(counts)} files' + (': ' + ', '.join(f'{r} ({n})' for r, n in list(counts.items())[:30]) if counts else '')
    if args.get('dry_run'): return 'dry run, nothing changed: ' + report
    exp = args.get('expected_count')
    if exp not in (None, '') and int(exp) != total: raise EditError(tr('expected_count={exp} اما {total} مورد پیدا شد؛ چیزی تغییر نکرد ({report})', exp=exp, total=total, report=report))
    mx = args.get('max_count')
    if mx not in (None, '') and total > int(mx): raise EditError(tr('{total} مورد بیشتر از max_count={mx} است؛ چیزی تغییر نکرد', total=total, mx=mx))
    if not total: raise EditError(tr('هیچ موردی پیدا نشد؛ چیزی تغییر نکرد'))
    for rel, new in new_texts.items(): sess.set_text(rel, new, note=tr('جایگزینی متن ({v0} مورد)', v0=counts[rel]))
    return 'replaced ' + report


def t_make_dir(sess, args):
    rel = core.clean_rel(str(args.get('path') or ''))
    return f'folder {rel} will be created' if sess.mkdir(rel) else f'folder {rel} already exists'


def _path_pairs(sess, src, dst, overwrite):
    if not sess.exists(src): raise EditError(tr('مسیر وجود ندارد: {src}', src=src))
    if sess.is_dir(dst) and not sess.is_dir(src): dst = posixpath.join(dst, posixpath.basename(src))
    elif sess.is_dir(dst) and sess.is_dir(src): dst = posixpath.join(dst, posixpath.basename(src))
    dst = core.clean_rel(dst); core.safe_path(sess.root, dst)
    if dst == src or dst.startswith(src + '/'): raise EditError(tr('مقصد نمی‌تواند خود مبدأ یا داخل آن باشد'))
    if sess.is_dir(src):
        files = sess.disk_files(src)
        if len(files) > MAX_PATH_FILES: raise EditError(tr('پوشه بیش از {MAX_PATH_FILES} فایل دارد', MAX_PATH_FILES=MAX_PATH_FILES))
        pairs = [(f, dst + f[len(src):]) for f in files]
    else:
        pairs = [(src, dst)]
    for a, b in pairs:
        core.safe_path(sess.root, b)
        if sess.exists(b) and not overwrite: raise EditError(tr('{b} از قبل وجود دارد (برای بازنویسی "overwrite": true)', b=b))
    return dst, pairs


def _copy_one(sess, a, b, note):
    f = sess._entry(a)
    if f.binary or f.raw is not None:
        data = sess.read_bytes(a)
        if len(data) > MAX_PATH_BYTES: raise EditError(tr('فایل بیش از حد بزرگ است'))
        sess.set_raw(b, data, note)
    else:
        sess.set_text(b, sess.text(a), info=sess.info(a), note=note)


def t_copy_path(sess, args):
    src = core.clean_rel(str(args.get('from') or '')); dst, pairs = _path_pairs(sess, src, str(args.get('to') or ''), args.get('overwrite'))
    for a, b in pairs: _copy_one(sess, a, b, tr('کپی از {a}', a=a))
    return f'copied {src} -> {dst} ({len(pairs)} files)'


def t_move_path(sess, args, ref_files):
    src = core.clean_rel(str(args.get('from') or '')); dst, pairs = _path_pairs(sess, src, str(args.get('to') or ''), args.get('overwrite'))
    folder = sess.is_dir(src)
    for a, b in pairs:
        _copy_one(sess, a, b, tr('منتقل‌شده از {a}', a=a)); sess.delete(a, prune=folder, note=tr('منتقل شد به {b}', b=b))
    msg = f'moved {src} -> {dst} ({len(pairs)} files)'
    if args.get('update_references', True):
        from app.project.references import update_references
        updated, notes = update_references(sess, dict(pairs), ref_files)
        if updated: msg += f'; updated references in {len(updated)} files: ' + ', '.join(updated[:20])
        if notes: msg += '; notes: ' + ' '.join(notes)
    return msg


# ----- unified diff -----------------------------------------------------------------------------------------------------
_HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def parse_patch(patch):
    """[(old_path|None, new_path|None, [hunk(lines)])] from a unified diff (git or plain)."""
    files = []; cur = None; hunk = None
    def clean(p):
        p = p.strip().split('\t')[0]
        if p == '/dev/null': return None
        if p[:2] in ('a/', 'b/'): p = p[2:]
        return p
    for line in patch.replace('\r\n', '\n').split('\n'):
        if line.startswith('--- '):
            cur = [clean(line[4:]), None, []]; files.append(cur); hunk = None
        elif line.startswith('+++ ') and cur is not None and cur[1] is None and not cur[2]:
            cur[1] = clean(line[4:])
        elif line.startswith('@@') and cur is not None:
            m = _HUNK.match(line)
            if not m: raise EditError(tr('سرآیند hunk نامعتبر: {v0}', v0=line[:60]))
            hunk = {'old_start': int(m.group(1)), 'old_count': int(m.group(2) if m.group(2) is not None else 1), 'lines': []}; cur[2].append(hunk)
        elif hunk is not None and line[:1] in (' ', '-', '+'):
            hunk['lines'].append(line)
        elif hunk is not None and line == '':
            hunk['lines'].append(' ')          # blank context line whose leading space was lost
        elif line.startswith('\\'):
            continue
    if not files: raise EditError(tr('patch هیچ فایلی ندارد (--- / +++ لازم است)'))
    return files


def apply_hunks(text, hunks, rel):
    """Apply hunks to text: exact context at the expected line, else the nearest unique exact (then whitespace-tolerant)
    match. Raises EditError when a hunk does not fit or is ambiguous."""
    lines = [l[:-1] if l.endswith('\n') else l for l in split_lines(text)]
    had_nl = text.endswith('\n') or not text; offset = 0
    for h in hunks:
        body = list(h['lines'])
        while body and body[-1] == ' ': body.pop()
        old = [l[1:] for l in body if l[0] in ' -']; new = [l[1:] for l in body if l[0] in ' +']
        want = (h['old_start'] if h['old_count'] == 0 else h['old_start'] - 1) + offset
        if not old:
            idx = max(0, min(want, len(lines)))
        else:
            def fits(i, loose):
                seg = lines[i:i + len(old)]
                return seg == old if not loose else [x.rstrip() for x in seg] == [x.rstrip() for x in old]
            idx = None
            for loose in (False, True):
                if 0 <= want <= len(lines) - len(old) and fits(want, loose): idx = want; break
                hits = sorted((i for i in range(len(lines) - len(old) + 1) if fits(i, loose)), key=lambda i: abs(i - want))
                if hits:
                    if len(hits) > 1 and abs(hits[0] - want) == abs(hits[1] - want):
                        raise EditError(tr('hunk @@ -{v0} در {rel} مبهم است (چند جا جور است)', v0=h["old_start"], rel=rel))
                    idx = hits[0]; break
            if idx is None: raise EditError(tr('hunk @@ -{v0} در {rel} با محتوای فعلی جور نیست؛ ابتدا read_file بگیرید', v0=h["old_start"], rel=rel))
        lines[idx:idx + len(old)] = new
        offset += len(new) - len(old)
    return '\n'.join(lines) + ('\n' if had_nl and lines else '')


def t_apply_patch(sess, args):
    patch = str(args.get('patch') or '')
    files = parse_patch(patch); done = []
    for old, new, hunks in files:
        if old is None and new is None: continue
        if old is None:          # new file
            text = ''.join(l[1:] + '\n' for h in hunks for l in h['lines'] if l[:1] == '+')
            if sess.exists(new): raise EditError(tr('{new} از قبل وجود دارد', new=new))
            sess.set_text(new, text, note=tr('فایل تازه از patch')); done.append(f'created {new}'); continue
        if new is None:
            sess.delete(old, note=tr('حذف با patch')); done.append(f'deleted {old}'); continue
        text = sess.text(old); result = apply_hunks(text, hunks, old)
        if new != old:
            sess.set_text(new, result, info=sess.info(old), note=tr('از {old} (patch)', old=old)); sess.delete(old, note=tr('تغییر نام به {new}', new=new))
        else:
            sess.set_text(old, result, note='patch')
        done.append(f'patched {new} ({len(hunks)} hunks)')
    return '; '.join(done)


# ----- dispatcher --------------------------------------------------------------------------------------------------------
def run_edit(sess, name, args, walk_files, ref_files):
    """Run one edit tool on the session atomically. Returns (ok, message)."""
    snap = sess.snapshot()
    try:
        if name in ('move_lines', 'copy_lines'): msg = t_lines(sess, args, name == 'move_lines')
        elif name == 'delete_lines': msg = t_delete_lines(sess, args)
        elif name == 'replace_lines': msg = t_replace_lines(sess, args)
        elif name == 'insert_text': msg = t_insert_text(sess, args)
        elif name == 'insert_file_content': msg = t_insert_file(sess, args)
        elif name == 'replace_text': msg = t_replace_text(sess, args, walk_files)
        elif name == 'make_dir': msg = t_make_dir(sess, args)
        elif name == 'copy_path': msg = t_copy_path(sess, args)
        elif name in ('move_path', 'rename_path'): msg = t_move_path(sess, args, ref_files)
        elif name == 'apply_patch': msg = t_apply_patch(sess, args)
        else: raise EditError(tr('ابزار ویرایش ناشناخته: {name}', name=name))
        return True, msg
    except (EditError, core.PathError, OSError) as e:
        sess.restore(snap)
        return False, str(e)


def plan_turn(root, ops, edit_calls, base_changes=()):
    """Plan one model turn: file/edit/delete blocks (``ops``) and edit tool calls (list of (pos, name, args, error)), in reply
    order, on one session seeded with still-pending earlier changes. Returns (changes, results) with results a list of
    (ok, message) per edit call."""
    from app.project.tools import _walk, _glob_match
    sess = EditSession(root, base_changes)
    errors = {}
    def walk_files(glob):
        return [r for r, _ in _walk(sess.root) if _glob_match(r, glob)]
    def ref_files():
        return [r for r, size in _walk(sess.root) if size <= REF_MAX_BYTES]
    items = [(op.pos, 0, i) for i, op in enumerate(ops)] + [(c[0], 1, i) for i, c in enumerate(edit_calls)]
    results = [None] * len(edit_calls)
    for _, kind, i in sorted(items):
        if kind == 1:
            pos, name, args, err = edit_calls[i]
            results[i] = (False, err) if err else run_edit(sess, name, args or {}, walk_files, ref_files)
            continue
        op = ops[i]
        if not op.complete and not op.error: continue
        try:
            if op.error: raise EditError(op.error)
            if op.kind == 'write': sess.set_text(op.path, op.content)
            elif op.kind == 'delete': sess.delete(op.path)
            elif op.kind == 'edit':
                current = sess.text(op.path) if sess.exists(op.path) else None
                for search, replace in op.pairs:
                    if current is None:
                        if search.strip() == '': current = replace; continue
                        raise EditError(tr('فایل وجود ندارد و SEARCH خالی نیست'))
                    if search.strip() == '' and current == '': current = replace; continue
                    current, note = core.find_replace(current, search, replace)
                    if note: sess._entry(op.path).notes.append(note)
                sess.set_text(op.path, current)
        except (EditError, ValueError, core.PathError) as e:
            errors.setdefault(op.path, str(e))
    changes = sess.changes()
    have = {c.path for c in changes}
    for path, err in errors.items():
        ch = next((c for c in changes if c.path == path), None)
        if ch is None:
            ch = core.Change(path, 'modify'); changes.append(ch)
        ch.error = err; ch.state = 'error'
    return changes, results
