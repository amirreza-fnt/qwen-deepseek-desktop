"""Best-effort update of import / require / include references after files are moved or renamed.

Handled (relative paths are resolved from the importing file, the new path is written in the same style):
* JS/TS/Vue/Svelte: ``import … from './x'``, ``import('./x')``, ``require('./x')``, ``export … from`` (extension-less and
  ``/index`` imports keep their style)
* CSS/SCSS/LESS: ``@import``/``@use``/``@forward`` and ``url(…)``; HTML: ``src``/``href``/``action``/``poster``
* PHP: ``require/include(_once) 'x.php'`` and ``__DIR__ . '/x.php'``; C/C++: ``#include "x.h"``
* Python: absolute module imports (``import a.b``, ``from a.b import c``, ``from a import b``)
* Java/Kotlin: the moved class's ``package`` line and ``import a.b.Class`` statements
* Go: import paths (``"module/dir"``) when a whole package folder moves (module name from go.mod)
* C#: namespaces are not path based, nothing to change (a note is returned)

Every change goes into the edit session, so it is shown in the review diff before anything is written.
"""
from app.i18n import tr
import posixpath, re

JS_EXT = ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte', '.astro')
JS_RESOLVE = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.vue', '.svelte', '.json', '.d.ts')
CSS_EXT = ('.css', '.scss', '.sass', '.less')
HTML_EXT = ('.html', '.htm', '.vue', '.svelte', '.php', '.cshtml', '.razor', '.jsx', '.tsx', '.astro')
C_EXT = ('.c', '.h', '.cpp', '.hpp', '.cc', '.hh', '.cxx', '.m', '.mm')

JS_SPEC = re.compile(r'''(\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s+)(['"`])(\.{1,2}/[^'"`\n]*)\2''')
CSS_SPEC = re.compile(r'''(@(?:import|use|forward)\s+(?:url\(\s*)?)(['"]?)([^'"()\s;]+)\2|(url\(\s*)(['"]?)([^'"()\s]+)\5''')
HTML_SPEC = re.compile(r'''(\b(?:src|href|action|poster|data-src)\s*=\s*)(['"])([^'"\n]+)\2''', re.I)
PHP_SPEC = re.compile(r'''(\b(?:require|include)(?:_once)?\b\s*\(?\s*(?:__DIR__\s*\.\s*)?)(['"])([^'"\n]+)\2''')
C_SPEC = re.compile(r'''(#\s*include\s*)(")([^"\n]+)"''')


def _external(spec):
    s = spec.strip().lower()
    return (not s or s.startswith(('http:', 'https:', '//', '#', 'data:', 'mailto:', 'tel:', 'javascript:', '{{', '{%', '<?', '$', '~', '@'))
            or '${' in s)


def _norm(path):
    p = posixpath.normpath(path)
    return '' if p == '.' else p


def _rel(target, from_dir):
    return posixpath.relpath(target, from_dir or '.')


def _split_suffix(spec):
    m = re.match(r'([^?#]*)(.*)$', spec)
    return m.group(1), m.group(2)


class _Ctx:
    def __init__(self, sess, mapping, files):
        self.sess = sess; self.mapping = mapping
        self.orig = set(files) | set(mapping)                 # files before the move
        self.reverse = {v: k for k, v in mapping.items()}

    def exists_orig(self, rel):
        return rel in self.orig


def _resolve_js(ctx, base_dir, spec):
    path = _norm(posixpath.join(base_dir, spec))
    if ctx.exists_orig(path): return path, 'exact'
    for ext in JS_RESOLVE:
        if ctx.exists_orig(path + ext): return path + ext, 'noext'
    for ext in JS_RESOLVE:
        if ctx.exists_orig(posixpath.join(path, 'index' + ext)): return posixpath.join(path, 'index' + ext), 'index'
    return None, ''


def _new_spec(target_new, new_dir, style, original, js):
    rel = _rel(target_new, new_dir)
    if style == 'noext':
        for ext in sorted(JS_RESOLVE, key=len, reverse=True):
            if rel.endswith(ext): rel = rel[:-len(ext)]; break
    elif style == 'index':
        if posixpath.basename(target_new).startswith('index.'): rel = _rel(posixpath.dirname(target_new), new_dir)
        else:
            for ext in sorted(JS_RESOLVE, key=len, reverse=True):
                if rel.endswith(ext): rel = rel[:-len(ext)]; break
    if js or original.startswith('./'):
        if not rel.startswith('.'): rel = './' + rel
    return rel


def _rewrite(ctx, text, regex, groups, old_file, new_file, kind):
    """Rewrite path specs in ``text`` (file moved old_file -> new_file, possibly the same)."""
    old_dir = posixpath.dirname(old_file); new_dir = posixpath.dirname(new_file); changed = [0]

    def repl(m):
        for prefix_g, quote_g, spec_g in groups:
            if m.group(spec_g) is None: continue
            spec = m.group(spec_g)
            if _external(spec): return m.group(0)
            body, suffix = _split_suffix(spec)
            leading_slash = kind == 'php' and body.startswith('/') and '__DIR__' in m.group(prefix_g)
            look = body.lstrip('/') if leading_slash else body
            if kind != 'js' and body.startswith('/') and not leading_slash: return m.group(0)
            if kind == 'js': target, style = _resolve_js(ctx, old_dir, look)
            else:
                target = _norm(posixpath.join(old_dir, look)); style = 'exact'
                if not ctx.exists_orig(target): target = None
            if not target or target.startswith('..'): return m.group(0)
            target_new = ctx.mapping.get(target, target)
            if target_new == target and new_file == old_file: return m.group(0)
            new = _new_spec(target_new, new_dir, style, look, kind == 'js')
            if kind != 'js' and not look.startswith('./') and new.startswith('./'): new = new[2:]
            if leading_slash: new = '/' + new
            new += suffix
            if new == spec: return m.group(0)
            changed[0] += 1
            start, end = m.span(spec_g); base = m.start()
            whole = m.group(0)
            return whole[:start - base] + new + whole[end - base:]
        return m.group(0)
    out = regex.sub(repl, text)
    return out, changed[0]


# ----- Python -------------------------------------------------------------------------------------------------------------------
def _py_names(rel, exists):
    if not rel.endswith('.py'): return []
    parts = rel[:-3].split('/')
    if parts[-1] == '__init__': parts = parts[:-1]
    if not parts: return []
    names = ['.'.join(parts)]
    # package-root form: drop leading folders that are not packages (no __init__.py), e.g. src/
    k = len(parts) - 1
    while k > 0 and exists('/'.join(parts[:k]) + '/__init__.py'): k -= 1
    if 0 < k < len(parts): names.append('.'.join(parts[k:]))
    return list(dict.fromkeys(names))


def _py_rewrite(text, pairs):
    count = 0
    for old, new in pairs:
        if old == new: continue
        o = re.escape(old)
        text, n1 = re.subn(rf'(?m)^(\s*from\s+){o}((?:\.\w+)*\s+import\b)', lambda m: m.group(1) + new + m.group(2), text)
        def imp(m):
            line, n = re.subn(rf'(?<![\w.]){o}(?=[\s,.]|$)', new, m.group(2))
            return m.group(1) + line if n else m.group(0)
        text, n2 = re.subn(rf'(?m)^(\s*import\s+)(.*\b{o}\b.*)$', imp, text)
        if '.' in old and '.' in new:
            op, on = old.rsplit('.', 1); np_, nn = new.rsplit('.', 1)
            text, n3 = re.subn(rf'(?m)^(\s*from\s+){re.escape(op)}(\s+import\s+){re.escape(on)}([ \t]+as[ \t]+\w+)?[ \t]*$',
                               lambda m: m.group(1) + np_ + m.group(2) + nn + (m.group(3) or '') + ('' if m.group(3) else (' as ' + on if nn != on else '')), text)
        else: n3 = 0
        count += n1 + n2 + n3
    return text, count


# ----- entry point ---------------------------------------------------------------------------------------------------------------
def update_references(sess, mapping, ref_files):
    """mapping: {old_rel: new_rel} of moved files. Returns (updated file list, notes)."""
    files = list(ref_files()); ctx = _Ctx(sess, mapping, files); updated = []; notes = []
    exists_after = lambda rel: sess.exists(rel)
    exists_before = lambda rel: rel in ctx.orig
    py_pairs = []
    for old, new in mapping.items():
        o = _py_names(old, exists_before); n = _py_names(new, exists_after)
        if o and n: py_pairs += list(zip(o, n + [n[-1]] * (len(o) - len(n))))
    java = _java_plan(sess, mapping, notes)
    go = _go_plan(sess, mapping, files, notes)
    if any(p.endswith('.cs') for p in mapping): notes.append(tr('C#: namespace‌ها به مسیر وابسته نیستند و تغییری نکردند.'))
    candidates = [f for f in files if f not in mapping] + list(mapping.values())
    for current in candidates:
        old_file = ctx.reverse.get(current, current)
        if not sess.exists(current) or sess.is_dir(current): continue
        try: text = sess.text(current)
        except Exception: continue
        ext = posixpath.splitext(current)[1].lower(); new_text = text; n = 0
        if ext in JS_EXT:
            new_text, k = _rewrite(ctx, new_text, JS_SPEC, [(1, 2, 3)], old_file, current, 'js'); n += k
        if ext in CSS_EXT or ext in ('.html', '.htm', '.vue', '.svelte'):
            new_text, k = _rewrite(ctx, new_text, CSS_SPEC, [(1, 2, 3), (4, 5, 6)], old_file, current, 'css'); n += k
        if ext in HTML_EXT:
            new_text, k = _rewrite(ctx, new_text, HTML_SPEC, [(1, 2, 3)], old_file, current, 'html'); n += k
        if ext == '.php':
            new_text, k = _rewrite(ctx, new_text, PHP_SPEC, [(1, 2, 3)], old_file, current, 'php'); n += k
        if ext in C_EXT:
            new_text, k = _rewrite(ctx, new_text, C_SPEC, [(1, 2, 3)], old_file, current, 'c'); n += k
        if ext == '.py' and py_pairs:
            new_text, k = _py_rewrite(new_text, py_pairs); n += k
        if ext in ('.java', '.kt') and java:
            new_text, k = java(current, new_text); n += k
        if ext == '.go' and go:
            new_text, k = go(new_text); n += k
        if n and new_text != text:
            sess.set_text(current, new_text, note=tr('به‌روزرسانی {n} ارجاع (import/require/include)', n=n)); updated.append(current)
    if any(p.endswith('.py') for p in mapping): notes.append(tr('Python: importهای نسبی (from . import) بررسی نشدند.'))
    return updated, notes


def _java_plan(sess, mapping, notes):
    renames = []   # (old_fqn, new_fqn, new_file, new_pkg)
    for old, new in mapping.items():
        if not old.endswith('.java'): continue
        try: text = sess.text(new)
        except Exception: continue
        m = re.search(r'(?m)^\s*package\s+([\w.]+)\s*;', text)
        if not m: continue
        pkg = m.group(1); old_dir = posixpath.dirname(old); pkg_path = pkg.replace('.', '/')
        if not (old_dir == pkg_path or old_dir.endswith('/' + pkg_path)): notes.append(tr('Java: مسیر {old} با package {pkg} جور نیست؛ تغییری داده نشد.', old=old, pkg=pkg)); continue
        src_root = old_dir[:len(old_dir) - len(pkg_path)].rstrip('/')
        new_dir = posixpath.dirname(new)
        if src_root and not (new_dir == src_root or new_dir.startswith(src_root + '/')):
            notes.append(tr('Java: {new} بیرون از ریشهٔ سورس است؛ package تغییر نکرد.', new=new)); continue
        new_pkg = (new_dir[len(src_root):] if src_root else new_dir).strip('/').replace('/', '.')
        oc = posixpath.splitext(posixpath.basename(old))[0]; nc = posixpath.splitext(posixpath.basename(new))[0]
        if oc != nc: notes.append(tr('Java: نام کلاس {oc} به {nc} تغییر نکرد؛ در صورت نیاز جداگانه ویرایش کنید.', oc=oc, nc=nc))
        renames.append((f'{pkg}.{oc}', f'{new_pkg}.{nc}', new, new_pkg, pkg))
    if not renames: return None

    def apply(current, text):
        n = 0
        for old_fqn, new_fqn, new_file, new_pkg, old_pkg in renames:
            if current == new_file and new_pkg != old_pkg:
                text, k = re.subn(rf'(?m)^(\s*package\s+){re.escape(old_pkg)}(\s*;)', lambda m: m.group(1) + new_pkg + m.group(2), text); n += k
            text, k = re.subn(rf'(?m)^(\s*import\s+(?:static\s+)?){re.escape(old_fqn)}(\s*;|\.)', lambda m: m.group(1) + new_fqn + m.group(2), text); n += k
        return text, n
    return apply


def _go_plan(sess, mapping, files, notes):
    gos = {o: n for o, n in mapping.items() if o.endswith('.go')}
    if not gos: return None
    try: mod = re.search(r'(?m)^\s*module\s+(\S+)', sess.text('go.mod')).group(1)
    except Exception: notes.append(tr('Go: go.mod پیدا نشد؛ import pathها تغییر نکردند.')); return None
    dirs = {}
    for o, n in gos.items(): dirs.setdefault(posixpath.dirname(o), set()).add(posixpath.dirname(n))
    pairs = []
    for od, nds in dirs.items():
        all_go = [f for f in files if f.endswith('.go') and posixpath.dirname(f) == od]
        if len(nds) == 1 and all(f in gos for f in all_go) and od != next(iter(nds)):
            nd = next(iter(nds)); pairs.append((f'{mod}/{od}' if od else mod, f'{mod}/{nd}' if nd else mod))
        elif od not in nds:
            notes.append(tr('Go: فقط بخشی از بستهٔ {v0} جابه‌جا شد؛ import pathها تغییر نکردند.', v0=od or "."))
    if not pairs: return None

    def apply(text):
        n = 0
        for old, new in pairs:
            text, k = re.subn(r'"' + re.escape(old) + r'(/[^"]*)?"', lambda m: '"' + new + (m.group(1) or '') + '"', text); n += k
        return text, n
    return apply
