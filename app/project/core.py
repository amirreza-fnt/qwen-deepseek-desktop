"""Project mode core (no Qt): safe paths, project scanning, prompt context, the file-operation protocol parser,
change planning (with whitespace-tolerant SEARCH matching), diffs, apply with backups, and undo.

Nothing here writes to disk except ``apply_changes`` / ``undo_last``, which the UI calls only after a user click.
Every path is resolved inside the project root; absolute paths, '..' and symlink escapes are rejected.
"""
from app.i18n import tr
import difflib, fnmatch, hashlib, json, os, re, shutil, time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

IGNORE_DIRS = {'.git', '.hg', '.svn', 'node_modules', 'venv', '.venv', 'env', 'dist', 'build', '__pycache__', '.mypy_cache',
               '.pytest_cache', '.idea', '.vs', '.vscode', '.tox', '.next', '.nuxt', 'target', 'bin', 'obj', '.gradle', '.cache'}
BINARY_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.pdf', '.zip', '.7z', '.rar', '.gz', '.tar', '.exe', '.dll',
              '.so', '.dylib', '.pyc', '.pyo', '.class', '.jar', '.mp3', '.mp4', '.wav', '.avi', '.mov', '.ttf', '.otf', '.woff', '.woff2',
              '.eot', '.db', '.sqlite', '.sqlite3', '.bin', '.dat', '.psd', '.lock', '.pdb', '.obj', '.o', '.a', '.lib', '.iso', '.msi'}
MAX_TREE_FILES = 3000
MAX_FILE_BYTES = 400_000          # files larger than this are listed but cannot be attached
MAX_ATTACH_CHARS = 60_000         # per attached file
CONTEXT_BUDGET_CHARS = 150_000    # whole project context (tree + attached files)


class PathError(ValueError):
    pass


def project_key(root):
    return hashlib.sha1(str(Path(root).resolve()).lower().encode('utf-8')).hexdigest()[:12]


def default_history_base():
    return Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'DeepSeekDesktop' / 'project-history'


def clean_rel(rel):
    """Validate a model/user supplied relative path and return it in posix form (no resolution yet)."""
    if not isinstance(rel, str): raise PathError(tr('مسیر نامعتبر است'))
    rel = rel.strip().strip('`"\'').replace('\\', '/')
    if not rel or '\x00' in rel: raise PathError(tr('مسیر خالی یا نامعتبر است'))
    if rel.startswith('/') or re.match(r'^[A-Za-z]:', rel) or rel.startswith('//'):
        raise PathError(tr('مسیر مطلق مجاز نیست: {rel}', rel=rel))
    while rel.startswith('./'): rel = rel[2:]
    parts = [p for p in rel.split('/') if p not in ('', '.')]
    if not parts: raise PathError(tr('مسیر خالی است'))
    if any(p == '..' for p in parts): raise PathError(tr('مسیر خارج از پوشهٔ پروژه است: {rel}', rel=rel))
    if any(re.search(r'[<>:"|?*]', p) or p.endswith(' ') or p.endswith('.') for p in parts):
        raise PathError(tr('نام فایل نامعتبر است: {rel}', rel=rel))
    if parts[0].lower() == '.git': raise PathError(tr('تغییر پوشهٔ .git مجاز نیست'))
    return '/'.join(parts)


def safe_path(root, rel):
    """Absolute path of ``rel`` inside ``root``; raises PathError for anything that would leave the root
    (absolute paths, '..', symlinks/junctions pointing outside)."""
    root_resolved = Path(root).resolve()
    rel = clean_rel(rel)
    target = (root_resolved / Path(*PurePosixPath(rel).parts)).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise PathError(tr('مسیر خارج از پوشهٔ پروژه است: {rel}', rel=rel))
    # also check every existing ancestor (a symlinked directory that points outside is rejected above by resolve())
    return target


# ----- scanning -----------------------------------------------------------------------------------------
def load_gitignore(root):
    patterns = []
    try:
        for line in (Path(root) / '.gitignore').read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('!'): continue
            patterns.append(line)
    except OSError:
        pass
    return patterns


def ignored(rel, is_dir, patterns):
    name = rel.rsplit('/', 1)[-1]
    if is_dir and name in IGNORE_DIRS: return True
    if not is_dir and os.path.splitext(name)[1].lower() in BINARY_EXT: return True
    for pat in patterns:
        dir_only = pat.endswith('/'); p = pat.rstrip('/')
        if dir_only and not is_dir: continue
        anchored = p.startswith('/') or '/' in p; p = p.lstrip('/')
        if anchored:
            if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + '/*'): return True
        elif fnmatch.fnmatch(name, p):
            return True
    return False


def scan(root, max_files=MAX_TREE_FILES):
    """List project files (posix relative paths with sizes), skipping ignored dirs/binaries; never follows
    symlinked directories."""
    root = Path(root); patterns = load_gitignore(root); out = []; truncated = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root).replace('\\', '/'); rel_dir = '' if rel_dir == '.' else rel_dir
        keep = []
        for d in sorted(dirnames):
            rel = f'{rel_dir}/{d}' if rel_dir else d
            if os.path.islink(os.path.join(dirpath, d)) or ignored(rel, True, patterns): continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            rel = f'{rel_dir}/{f}' if rel_dir else f
            full = os.path.join(dirpath, f)
            if os.path.islink(full) or ignored(rel, False, patterns): continue
            try: size = os.path.getsize(full)
            except OSError: continue
            out.append((rel, size))
            if len(out) >= max_files: truncated = True; break
        if truncated: break
    return out, truncated


def tree_text(files, truncated=False, limit=12_000):
    """Compact indented tree of the scanned files."""
    lines = []; seen_dirs = set()
    for rel, size in files:
        parts = rel.split('/')
        for i in range(len(parts) - 1):
            d = '/'.join(parts[:i + 1])
            if d not in seen_dirs: seen_dirs.add(d); lines.append('  ' * i + parts[i] + '/')
        lines.append('  ' * (len(parts) - 1) + parts[-1])
    text = '\n'.join(lines)
    if len(text) > limit: text = text[:limit].rsplit('\n', 1)[0] + '\n… (tree truncated)'
    elif truncated: text += '\n… (more files not listed)'
    return text


# ----- text files: encoding, BOM and line endings are preserved -------------------------------------------
@dataclass
class TextInfo:
    text: str
    bom: bool = False
    newline: str = '\n'


def read_text(path):
    data = Path(path).read_bytes()
    if b'\x00' in data[:8000]: raise UnicodeError('binary file')
    bom = data.startswith(b'\xef\xbb\xbf')
    text = data[3:].decode('utf-8') if bom else data.decode('utf-8')
    crlf = text.count('\r\n'); lf = text.count('\n') - crlf
    newline = '\r\n' if crlf > lf else '\n'
    return TextInfo(text.replace('\r\n', '\n'), bom, newline)


def encode_text(text, info):
    body = text.replace('\r\n', '\n')
    if info.newline == '\r\n': body = body.replace('\n', '\r\n')
    return (b'\xef\xbb\xbf' if info.bom else b'') + body.encode('utf-8')


# ----- prompt -----------------------------------------------------------------------------------------------
PROJECT_INSTRUCTION = """[Project mode. You are editing files in the user's local project folder. The app applies your changes only after the user reviews them. Use EXACTLY these formats for file operations (paths are relative to the project root, forward slashes, never absolute, never ".."):

1) Create a file or replace its whole content:
```file:relative/path.ext
<complete new file content>
```

2) Edit part of an existing file (one or more SEARCH/REPLACE pairs; SEARCH must copy the current lines exactly, including indentation, and must be unique in the file; keep SEARCH short):
```edit:relative/path.ext
<<<<<<< SEARCH
<exact existing lines>
=======
<new lines>
>>>>>>> REPLACE
```

3) Delete a file:
```delete:relative/path.ext
```

If the file content itself contains ``` use four backticks (````file:path ... ````) for that block. Never put "..." or placeholders instead of real code. Do not use your built-in tools (code interpreter, artifacts or canvas). Write explanations outside the blocks, in the same language as the user (Persian if the user writes Persian). If no file change is needed, answer normally.]"""


def mention_paths(text, files):
    """Files mentioned as @path or @name (unique basename) in the user text."""
    names = {}; paths = {rel for rel, _ in files}
    for rel in paths: names.setdefault(rel.rsplit('/', 1)[-1].lower(), []).append(rel)
    found = []
    for m in re.finditer(r'(?<![\w@])@([\w.\-/\\]+[\w])', text):
        token = m.group(1).replace('\\', '/')
        if token in paths: found.append(token)
        elif len(names.get(token.lower(), [])) == 1: found.append(names[token.lower()][0])
    return list(dict.fromkeys(found))


def file_context(root, rels):
    """Attached files as prompt text plus a report [(rel, chars, note)]."""
    parts = []; report = []
    for rel in rels:
        try:
            path = safe_path(root, rel)
            if path.stat().st_size > MAX_FILE_BYTES: report.append((rel, 0, 'too_large')); continue
            text = read_text(path).text
        except (OSError, UnicodeError, PathError):
            report.append((rel, 0, 'unreadable')); continue
        note = ''
        if len(text) > MAX_ATTACH_CHARS: text = text[:MAX_ATTACH_CHARS]; note = 'truncated'
        fence = '````' if '```' in text else '```'
        parts.append(f'Current content of {rel}' + (' (TRUNCATED — do not rewrite this file completely, use edit blocks)' if note else '') +
                     f':\n{fence}\n{text}\n{fence}')
        report.append((rel, len(text), note))
    return '\n\n'.join(parts), report


def build_prompt(root, user_text, attached, files=None, truncated=False, tools=False):
    """The message actually sent in project mode: protocol instruction (+ app tools) + compact tree + attached files + request."""
    if files is None: files, truncated = scan(root)
    tree = tree_text(files, truncated)
    rels = list(dict.fromkeys(list(attached) + mention_paths(user_text, files)))
    ctx, report = file_context(root, rels)
    extra = ''
    if tools:
        from app.project.tools import tools_instruction
        extra = '\n\n' + tools_instruction()
    prompt = (PROJECT_INSTRUCTION + extra + f'\n\nProject folder name: {Path(root).name}\nProject files:\n```text\n{tree}\n```\n\n' +
              (ctx + '\n\n' if ctx else '') + 'User request:\n' + user_text)
    return prompt, report


def context_size(root, attached, files):
    total = len(tree_text(files)) + len(PROJECT_INSTRUCTION)
    sizes = dict(files)
    for rel in attached: total += min(sizes.get(rel, 0), MAX_ATTACH_CHARS)
    return total


# ----- protocol parser ------------------------------------------------------------------------------------------
@dataclass
class Op:
    kind: str            # 'write' | 'edit' | 'delete'
    path: str
    content: str = ''
    pairs: list = field(default_factory=list)   # [(search, replace)] for edit
    complete: bool = True
    error: str = ''
    pos: int = 0             # offset of the block in the reply (keeps blocks and edit tools in reply order)

_OPEN = re.compile(r'^(`{3,})[ \t]*(file|edit|delete)[ \t]*:[ \t]*(.+?)[ \t]*$', re.M)
_SR = re.compile(r'^<{5,9} ?SEARCH[^\n]*\n(.*?)^={5,9}[ \t]*\n(.*?)^>{5,9} ?REPLACE[^\n]*$', re.M | re.S)


def parse_ops(text, final=True):
    """Operations in a (possibly still streaming) reply. Incomplete trailing blocks are returned with
    complete=False (shown as progress, never applied)."""
    ops = []; pos = 0
    while True:
        m = _OPEN.search(text, pos)
        if not m: break
        fence, kind, raw_path = m.group(1), m.group(2), m.group(3)
        body_start = m.end() + 1
        close = re.compile(r'^' + fence + r'[ \t]*$', re.M).search(text, body_start) if body_start <= len(text) else None
        body = text[body_start:close.start()] if close else text[body_start:]
        if body.endswith('\n'): body = body[:-1]
        try: path = clean_rel(raw_path)
        except PathError as e: path, err = raw_path.strip(), str(e)
        else: err = ''
        op = Op('write' if kind == 'file' else kind, path, complete=close is not None, error=err, pos=m.start())
        if kind == 'file': op.content = body + ('\n' if body and close else '')
        elif kind == 'edit':
            op.pairs = [(s, r) for s, r in _SR.findall(body + '\n')]
            if close and not op.pairs and not err: op.error = tr('بلوک SEARCH/REPLACE معتبری پیدا نشد')
        ops.append(op)
        if not close: break
        pos = close.end()
    if final:
        for op in ops:
            if not op.complete and not op.error: op.error = tr('بلوک ناتمام ماند (پاسخ قطع شد)')
    return ops


# ----- planning ----------------------------------------------------------------------------------------------------
@dataclass
class Change:
    path: str
    kind: str                 # 'create' | 'modify' | 'delete'
    old: str = None           # None when the file does not exist
    new: str = None           # None for delete
    info: TextInfo = None
    error: str = ''
    notes: list = field(default_factory=list)
    state: str = 'pending'    # pending | applied | rejected | error
    raw: bytes = None         # binary content for a created file (copy/move of a non-text file)
    prune: bool = False       # delete: also remove parent folders left empty (move of a folder)


def _indent(line):
    return line[:len(line) - len(line.lstrip(' \t'))]


def find_replace(text, search, replace):
    """Apply one SEARCH/REPLACE to text. Exact unique match first; otherwise a whitespace-tolerant line match
    that must also be unique. Returns (new_text, note); raises ValueError (Persian message) when not applicable."""
    if search == '':
        raise ValueError(tr('SEARCH خالی است'))
    count = text.count(search)
    if count == 1: return text.replace(search, replace, 1), ''
    if count > 1: raise ValueError(tr('متن SEARCH در فایل {count} بار پیدا شد؛ مبهم است و اعمال نشد', count=count))
    t_lines = text.split('\n'); s_lines = search.strip('\n').split('\n'); r_lines = replace.strip('\n').split('\n') if replace.strip('\n') else []
    norm = lambda l: ' '.join(l.split())
    s_norm = [norm(l) for l in s_lines]
    while s_norm and not s_norm[0]: s_norm.pop(0); s_lines.pop(0)
    while s_norm and not s_norm[-1]: s_norm.pop(); s_lines.pop()
    if not s_norm: raise ValueError(tr('SEARCH خالی است'))
    hits = [i for i in range(len(t_lines) - len(s_norm) + 1) if [norm(l) for l in t_lines[i:i + len(s_norm)]] == s_norm]
    if not hits: raise ValueError(tr('متن SEARCH در فایل پیدا نشد (حتی با نادیده‌گرفتن فاصله‌ها)'))
    if len(hits) > 1: raise ValueError(tr('متن SEARCH با نادیده‌گرفتن فاصله‌ها {v0} جا پیدا شد؛ مبهم است و اعمال نشد', v0=len(hits)))
    i = hits[0]
    # map the model's indentation to the file's indentation using the matched lines
    mapping = {}
    for k, l in enumerate(s_lines):
        if l.strip(): mapping.setdefault(_indent(l), _indent(t_lines[i + k]))
    keys = sorted(mapping, key=len, reverse=True)
    def reindent(line):
        if not line.strip(): return line
        ind = _indent(line)
        if ind in mapping: return mapping[ind] + line[len(ind):]
        for key in keys:
            if ind.startswith(key): return mapping[key] + line[len(key):]
        return line
    new_lines = t_lines[:i] + [reindent(l) for l in r_lines] + t_lines[i + len(s_norm):]
    return '\n'.join(new_lines), tr('با تطبیق تقریبی (فاصله‌ها نادیده گرفته شد)')


def plan_changes(root, ops):
    """One Change per path, applying the ops for that path in order (in memory only)."""
    changes = {}; order = []
    for op in ops:
        if not op.complete and not op.error: continue
        ch = changes.get(op.path)
        if ch is None:
            ch = Change(op.path, 'modify'); changes[op.path] = ch; order.append(op.path)
            try:
                path = safe_path(root, op.path)
                if path.exists():
                    if path.is_dir(): raise PathError(tr('{path} یک پوشه است', path=op.path))
                    if path.stat().st_size > MAX_FILE_BYTES * 5 and op.kind != 'delete': raise PathError(tr('فایل بیش از حد بزرگ است'))
                    if op.kind != 'delete' or True:
                        try: ch.info = read_text(path); ch.old = ch.info.text
                        except UnicodeError:
                            if op.kind != 'delete': raise PathError(tr('فایل متنی UTF-8 نیست؛ تغییر آن پشتیبانی نمی‌شود'))
                            ch.old = ''; ch.info = TextInfo('')
                ch.new = ch.old
            except (PathError, OSError) as e:
                ch.error = str(e)
        if op.error and not ch.error: ch.error = op.error
        if ch.error: continue
        if op.kind == 'write':
            ch.new = op.content
        elif op.kind == 'delete':
            if ch.old is None and ch.new is None: ch.error = tr('فایلی برای حذف وجود ندارد')
            ch.new = None
        elif op.kind == 'edit':
            current = ch.new
            for search, replace in op.pairs:
                if current is None:
                    if search.strip() == '': current = replace; continue
                    ch.error = tr('فایل وجود ندارد و SEARCH خالی نیست'); break
                if search.strip() == '' and current == '': current = replace; continue
                try:
                    current, note = find_replace(current, search, replace)
                    if note and note not in ch.notes: ch.notes.append(note)
                except ValueError as e:
                    ch.error = str(e); break
            if not ch.error: ch.new = current
    result = []
    for path in order:
        ch = changes[path]
        if ch.error: ch.state = 'error'
        elif ch.new is None: ch.kind = 'delete'
        elif ch.old is None: ch.kind = 'create'
        else: ch.kind = 'modify'
        if not ch.error and ch.kind == 'modify' and ch.new == ch.old: ch.notes.append(tr('بدون تغییر'))
        result.append(ch)
    return result


def unified_diff(change, context=3):
    old = (change.old or '').splitlines(); new = (change.new or '').splitlines()
    return list(difflib.unified_diff(old, new, 'a/' + change.path, 'b/' + change.path, lineterm='', n=context))


def diff_stats(change):
    plus = minus = 0
    for line in unified_diff(change, 0):
        if line.startswith('+') and not line.startswith('+++'): plus += 1
        elif line.startswith('-') and not line.startswith('---'): minus += 1
    return plus, minus


# ----- apply / undo ---------------------------------------------------------------------------------------------------
def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.dsd-tmp')
    with open(tmp, 'wb') as f: f.write(data)
    os.replace(tmp, path)


def apply_changes(root, changes, history_base=None):
    """Write the given changes (after backing up the originals). Returns the history entry folder.
    Re-checks that each file still has the content the change was planned against."""
    root = Path(root).resolve(); history_base = Path(history_base or default_history_base())
    todo = [c for c in changes if c.state == 'pending' and not c.error]
    if not todo: return None
    entry = history_base / project_key(root) / time.strftime('%Y%m%d-%H%M%S') 
    n = 0
    while entry.exists(): n += 1; entry = entry.with_name(entry.name.split('_')[0] + f'_{n}')
    (entry / 'files').mkdir(parents=True)
    manifest = {'root': str(root), 'time': time.time(), 'files': []}
    paths = []
    for ch in todo:                                   # validate everything before touching anything
        path = safe_path(root, ch.path)
        if ch.kind == 'mkdir':
            if path.exists() and not path.is_dir(): raise PathError(tr('{path} یک فایل است', path=ch.path))
            paths.append(path); continue
        if path.exists():
            current = read_text(path).text if ch.kind != 'delete' else None
            if ch.old is None: raise PathError(tr('{path} در این فاصله ساخته شده است؛ دوباره بررسی کنید', path=ch.path))
            if current is not None and current != ch.old: raise PathError(tr('{path} پس از پیشنهاد تغییر کرده است؛ دوباره بررسی کنید', path=ch.path))
        elif ch.old is not None:
            raise PathError(tr('{path} دیگر وجود ندارد', path=ch.path))
        paths.append(path)
    for i, (ch, path) in enumerate(zip(todo, paths)):
        if ch.kind == 'mkdir':
            manifest['files'].append({'path': ch.path, 'existed': path.exists(), 'dir': True}); continue
        record = {'path': ch.path, 'existed': path.exists()}
        if path.exists():
            backup = entry / 'files' / f'{i}.bak'; shutil.copy2(path, backup); record['backup'] = backup.name
        manifest['files'].append(record)
    (entry / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    created_dirs = []
    for ch, path in zip(todo, paths):
        if ch.kind == 'mkdir':
            path.mkdir(parents=True, exist_ok=True)
        elif ch.kind == 'delete':
            path.unlink()
            if ch.prune:
                parent = path.parent
                while parent != root and root in parent.parents and not any(parent.iterdir()):
                    parent.rmdir(); parent = parent.parent
        elif ch.raw is not None:
            _atomic_write(path, ch.raw)
        else:
            info = ch.info or TextInfo('', False, '\n')
            _atomic_write(path, encode_text(ch.new, info))
        ch.state = 'applied'
    return entry


def history_entries(root, history_base=None):
    base = Path(history_base or default_history_base()) / project_key(root)
    if not base.exists(): return []
    return sorted([p for p in base.iterdir() if p.is_dir() and not p.name.endswith('.undone') and (p / 'manifest.json').exists()], key=lambda p: p.name)


def undo_last(root, history_base=None):
    """Restore the files of the latest apply (re-create/overwrite from backup; remove files that it created).
    Returns the list of restored relative paths, or [] when there is nothing to undo."""
    entries = history_entries(root, history_base)
    if not entries: return []
    entry = entries[-1]; manifest = json.loads((entry / 'manifest.json').read_text(encoding='utf-8'))
    restored = []
    for record in reversed(manifest['files']):
        path = safe_path(root, record['path'])
        if record.get('dir'):
            if not record.get('existed') and path.is_dir() and not any(path.iterdir()): path.rmdir()
        elif record.get('existed'):
            data = (entry / 'files' / record['backup']).read_bytes(); _atomic_write(path, data)
        elif path.exists():
            path.unlink()
        restored.append(record['path'])
    entry.rename(entry.with_name(entry.name + '.undone'))   # kept for reference, no longer "last"
    return restored
