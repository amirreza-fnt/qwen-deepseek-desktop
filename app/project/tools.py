"""Project-mode agent tools (no Qt).

The model asks for a tool with a fenced text block::

    ```tool:read_file
    {"path": "src/app.js"}
    ```

The app parses the blocks (``parse_calls``), runs them (``execute``) and sends the results back (``format_results``).
Read-only tools (list_dir, find_files, search, read_file, image_info) and HTTP requests to localhost run automatically and
are sandboxed to the project folder. run_command, download_file and HTTP requests to other hosts run only after the user
clicks «اجرا» (``needs_approval``); with the session toggle, read-only commands (``is_readonly_command``) may run directly.

Nothing here logs arguments, outputs or message text.
"""
from app.i18n import tr
import fnmatch, ipaddress, json, os, re, signal, struct, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from app.project import core

MAX_OUTPUT_CHARS = 20_000        # per tool result sent to the model
COMMAND_TIMEOUT = 120            # seconds (default for run_command)
MAX_COMMAND_TIMEOUT = 600
HTTP_TIMEOUT = 30
MAX_HTTP_BYTES = 2_000_000
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_READ_CHARS = 40_000
MAX_LIST_ENTRIES = 600
MAX_SEARCH_MATCHES = 200
MAX_SEARCH_FILE_BYTES = 2_000_000
MAX_STEPS = 10                   # tool rounds per user message
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.svg', '.tif', '.tiff', '.avif'}

# name -> (primary argument, allowed arguments)
TOOLS = {
    'list_dir': ('path', {'path', 'depth'}),
    'find_files': ('pattern', {'pattern', 'path'}),
    'search': ('pattern', {'pattern', 'glob', 'path', 'regex', 'case_sensitive'}),
    'read_file': ('path', {'path', 'start_line', 'end_line'}),
    'image_info': ('path', {'path'}),
    'http_request': ('url', {'url', 'method', 'headers', 'body', 'json', 'timeout'}),
    'download_file': ('url', {'url', 'path', 'overwrite'}),
    'run_command': ('command', {'command', 'timeout', 'shell'}),
    'count_lines': ('path', {'path', 'glob'}),
}
from app.project.edits import EDIT_TOOLS
TOOLS.update(EDIT_TOOLS)
ALIASES = {'ls': 'list_dir', 'list': 'list_dir', 'tree': 'list_dir', 'glob': 'find_files', 'find': 'find_files', 'grep': 'search',
           'read': 'read_file', 'cat': 'read_file', 'image': 'image_info', 'http': 'http_request', 'fetch': 'http_request',
           'request': 'http_request', 'download': 'download_file', 'shell': 'run_command', 'command': 'run_command',
           'run': 'run_command', 'terminal': 'run_command', 'powershell': 'run_command', 'cmd': 'run_command', 'bash': 'run_command'}
READ_ONLY_TOOLS = {'list_dir', 'find_files', 'search', 'read_file', 'image_info', 'count_lines'}
ALIASES.update({'move': 'move_path', 'rename': 'rename_path', 'mv': 'move_path', 'cp': 'copy_path', 'mkdir': 'make_dir',
                'patch': 'apply_patch', 'sed': 'replace_text', 'replace': 'replace_text', 'wc': 'count_lines',
                'cut_lines': 'move_lines', 'extract_lines': 'move_lines', 'remove_lines': 'delete_lines'})


def shell_name():
    return 'PowerShell' if os.name == 'nt' else 'bash'


def tools_instruction():
    sh = shell_name()
    return ('[App tools (project mode). ONLY when the user\'s request about this project needs it, ask the app to run a tool by '
            'writing a block exactly like this (arguments as one JSON object):\n'
            '```tool:read_file\n{"path": "src/app.js"}\n```\n'
            'Look-up tools (run automatically):\n'
            '- list_dir {"path": ".", "depth": 2}: folder structure\n'
            '- find_files {"pattern": "**/*.png"}: find files by name/glob\n'
            '- search {"pattern": "text", "glob": "*.js", "regex": false}: search inside files (grep, shows line numbers)\n'
            '- read_file {"path": "src/a.js", "start_line": 1, "end_line": 400}: read a file WITH LINE NUMBERS\n'
            '- count_lines {"path": "src"} or {"glob": "**/*.py"}: line counts\n'
            '- image_info {"path": "img/logo.png"}: image format, width/height and file size\n'
            '- http_request {"method": "GET", "url": "http://localhost:3000/api/items", "headers": {}, "json": null}: test an API\n'
            '- download_file {"url": "https://example.com/a.jpg", "path": "assets/a.jpg"}: save a file inside the project\n'
            f'- run_command {{"command": "npm test"}}: run a {sh} command in the project folder (timeout {COMMAND_TIMEOUT} s'
            + (', use "shell": "cmd" for cmd.exe' if os.name == 'nt' else '') + ')\n'
            'Edit tools (the app does the work and shows the user a diff to apply; any language or file type):\n'
            '- move_lines {"from": "a.js", "start": 10, "end": 42, "start_marker": "function total", "end_marker": "}", "to": "lib/total.js", '
            '"position": "end"}: cut lines and insert them elsewhere (same or other file; a new file is created). Destination: "position": '
            '"start"/"end", or "to_line": N (insert before line N), or "after"/"before": "unique text of a line". Optional "indent": +4, -2 or "auto".\n'
            '- copy_lines: same arguments as move_lines, keeps the original\n'
            '- delete_lines {"path": "a.js", "start": 5, "end": 9, "start_marker": "...", "end_marker": "..."}\n'
            '- replace_lines {"path": "a.js", "start": 5, "end": 9, "text": "new short text"}\n'
            '- insert_text {"path": "a.js", "after": "import React", "text": "import x from \'./x\';"}\n'
            '- insert_file_content {"from": "snippets/a.html", "to": "index.html", "before": "</body>"}\n'
            '- replace_text {"pattern": "oldName", "replacement": "newName", "glob": "src/**/*.ts", "regex": false, "expected_count": 7} '
            '(or "path" for one file; "dry_run": true only counts; regex groups as $1)\n'
            '- move_path / rename_path {"from": "src/old.js", "to": "src/utils/new.js"}: files or folders; imports/require/include '
            'references are updated automatically (JS/TS, Python, PHP, CSS, HTML, C/C++, Java, Go)\n'
            '- copy_path {"from": "a", "to": "b"}, make_dir {"path": "src/components"}\n'
            '- apply_patch: a unified diff (--- a/file, +++ b/file, @@ hunks) as the block body\n'
            'For multi-line "text" you may write the JSON on the first line and the raw text on the next lines (no escaping).\n'
            'RULES: To change existing code ALWAYS prefer the edit tools over rewriting it: first read_file (line numbers), then refer '
            'to line ranges (add start_marker/end_marker copied from the first/last line for safety). Never retype code that only '
            'moves, is copied, renamed or deleted. Within one reply, edits run in order and later line numbers must account for earlier '
            'edits in the same file (simplest: edit a file bottom-up). Use ```file:path``` blocks only for genuinely new code and '
            '```edit:path``` SEARCH/REPLACE only for small changes. run_command, download_file and requests to non-local URLs run '
            'only after the user approves them. You may write several tool blocks in one reply; after look-up tools STOP and wait: the '
            'app sends the results in the next message. Never invent tool results. Paths are relative to the project folder. Do NOT '
            'use tools for greetings, small talk or anything you can answer directly; then just answer in plain text. When you have '
            'enough information, give the final answer without look-up tools.]')


# ----- parsing -----------------------------------------------------------------------------------------------------------
@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    complete: bool = True
    error: str = ''
    pos: int = 0

    def summary(self):
        return call_summary(self.name, self.args)


_TOOL_OPEN = re.compile(r'^(`{3,})[ \t]*tool[ \t]*:[ \t]*([A-Za-z_][\w\-]*)[ \t]*$', re.M)
_KV = re.compile(r'^\s*([A-Za-z_]\w*)\s*[:=]\s*(.*?)\s*$')


def _parse_args(name, body):
    primary, allowed = TOOLS[name]
    text = body.strip()
    if not text: return {}
    if text.startswith('{'):
        first, _, rest = text.partition('\n')
        try: value = json.loads(text)
        except ValueError:
            # {"path": "a.js", "after": "x"} on the first line, raw multi-line text below it (no JSON escaping needed)
            text_key = 'text' if 'text' in allowed else ('patch' if 'patch' in allowed else None)
            if text_key and rest.strip():
                try:
                    value = json.loads(first)
                    if isinstance(value, dict) and text_key not in value:
                        value[text_key] = rest[:-1] if body.endswith('\n') and rest.endswith('\n') else rest
                        return value
                except ValueError: pass
            # models often write Windows paths without escaping the backslashes: "C:\Users\x" -> "C:\\Users\\x"
            try: value = json.loads(re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', text))
            except ValueError: raise ValueError(tr('آرگومان‌ها JSON معتبر نیستند'))
        if not isinstance(value, dict): raise ValueError(tr('آرگومان‌ها باید یک شیء JSON باشند'))
        return value
    lines = [l for l in text.split('\n') if l.strip()]
    pairs = [_KV.match(l) for l in lines]
    if pairs and all(pairs) and all(m.group(1) in allowed for m in pairs):
        out = {}
        for m in pairs:
            v = m.group(2)
            try: out[m.group(1)] = json.loads(v)
            except ValueError: out[m.group(1)] = v.strip('"\'') if m.group(1) != primary or name != 'run_command' else v
        return out
    return {primary: text}


def parse_calls(text, final=True):
    """Tool calls in a (possibly still streaming) reply. Unterminated trailing blocks are complete=False."""
    calls = []; pos = 0
    while True:
        m = _TOOL_OPEN.search(text, pos)
        if not m: break
        fence, raw_name = m.group(1), m.group(2).lower().replace('-', '_')
        body_start = m.end() + 1
        close = re.compile(r'^' + fence + r'[ \t]*$', re.M).search(text, body_start) if body_start <= len(text) else None
        body = text[body_start:close.start()] if close else text[body_start:]
        name = ALIASES.get(raw_name, raw_name)
        call = ToolCall(name, complete=close is not None, pos=m.start())
        if name not in TOOLS:
            call.error = tr('ابزار ناشناخته: {raw_name}', raw_name=raw_name)
        elif close is not None:
            try: call.args = _parse_args(name, body)
            except ValueError as e: call.error = str(e)
        if final and not call.complete and not call.error: call.error = tr('بلوک ابزار ناتمام ماند')
        calls.append(call)
        if not close: break
        pos = close.end()
    return calls


def call_summary(name, args):
    args = args or {}
    if name == 'run_command': return str(args.get('command', ''))
    if name in ('http_request',): return f"{str(args.get('method') or 'GET').upper()} {args.get('url', '')}"
    if name == 'download_file': return f"{args.get('url', '')} → {args.get('path') or tr('(نام از نشانی)')}"
    if name in ('move_lines', 'copy_lines'):
        rng = f"{args.get('start', '?')}-{args.get('end', args.get('start', '?'))}" if args.get('start') else str(args.get('start_marker', ''))
        return f"{args.get('from', '')}:{rng} → {args.get('to') or args.get('from', '')}"
    if name in ('delete_lines', 'replace_lines'):
        return f"{args.get('path', '')}:{args.get('start', args.get('start_marker', '?'))}-{args.get('end', '')}".rstrip('-')
    if name in ('move_path', 'rename_path', 'copy_path', 'insert_file_content'): return f"{args.get('from', '')} → {args.get('to', '')}"
    if name == 'replace_text': return f"{args.get('pattern', '')} → {args.get('replacement', '')}  [{args.get('path') or args.get('glob') or ''}]"
    if name == 'apply_patch':
        files = re.findall(r'(?m)^\+\+\+ (?:b/)?(\S+)', str(args.get('patch', '')))
        return 'patch: ' + ', '.join(files[:5])
    if name == 'count_lines': return str(args.get('path') or args.get('glob') or '.')
    if name in ('find_files', 'search'): return str(args.get('pattern', '')) + (f"  [{args['glob']}]" if args.get('glob') else '')
    return str(args.get('path') or '.')


# ----- approval ---------------------------------------------------------------------------------------------------------
def is_local_url(url):
    try: host = (urllib.parse.urlsplit(str(url)).hostname or '').lower()
    except ValueError: return False
    if host in ('localhost', '0.0.0.0') or host.endswith('.localhost'): return True
    try: return ipaddress.ip_address(host).is_loopback
    except ValueError: return False


_RO_COMMANDS = {'dir', 'ls', 'gci', 'get-childitem', 'type', 'cat', 'gc', 'get-content', 'tree', 'where', 'where.exe', 'which',
                'get-command', 'gcm', 'pwd', 'get-location', 'echo', 'write-output', 'findstr', 'select-string', 'sls', 'get-item', 'gi',
                'get-itemproperty', 'test-path', 'resolve-path', 'measure-object', 'measure', 'select-object', 'select', 'sort-object',
                'sort', 'format-table', 'ft', 'format-list', 'fl', 'out-string', 'get-filehash', 'head', 'tail', 'wc', 'grep', 'rg',
                'file', 'stat', 'du', 'whoami', 'hostname', 'ver', 'get-date', 'date', 'more', 'get-psdrive'}
_GIT_RO = {'status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', 'blame', 'describe', 'shortlog', 'grep'}
_VERSION_TOOLS = {'python', 'python3', 'py', 'node', 'npm', 'npx', 'pip', 'pip3', 'git', 'dotnet', 'java', 'go', 'cargo', 'rustc',
                  'php', 'ruby', 'deno', 'bun', 'yarn', 'pnpm', 'composer', 'gcc', 'cmake', 'tsc', 'flutter', 'dart'}


def is_readonly_command(command):
    """Conservative check used only for the optional session toggle: plain listing/reading/version/git-status commands,
    no redirection, chaining, sub-expressions or scripts."""
    cmd = str(command or '').strip()
    if not cmd or '\n' in cmd or '\r' in cmd or re.search(r'[;&<>`^${}%~]|@\(|\|\|', cmd): return False
    # stay inside the project folder: no absolute paths, drive letters, UNC paths or '..'
    if re.search(r'\.\.|[A-Za-z]:|(^|\s)[\\/]', cmd): return False
    for seg in cmd.split('|'):
        tokens = seg.strip().split()
        if not tokens: return False
        head = tokens[0].lower(); rest = [t.lower() for t in tokens[1:]]
        if head.endswith('.exe') and head != 'where.exe': head = head[:-4]
        if head in _RO_COMMANDS:
            if any(t.startswith(('-out', '--output', '-exec', '-delete', '-fprint')) for t in rest): return False
            continue
        if head == 'git' and rest:
            sub = rest[0]
            if sub in _GIT_RO and not any(t.startswith(('--output', '--ext-diff', '-o')) for t in rest[1:]): continue
            if sub in ('branch', 'remote', 'tag') and all(t in ('-a', '-v', '-vv', '-r', '--list', '-l') for t in rest[1:]): continue
            if rest in (['--version'], ['version']): continue
            return False
        if head in _VERSION_TOOLS and rest in (['--version'], ['-v'], ['version'], ['-version']): continue
        return False
    return True


def needs_approval(call, allow_readonly_commands=False):
    if call.error: return False
    if call.name == 'run_command':
        return not (allow_readonly_commands and is_readonly_command(call.args.get('command')))
    if call.name == 'download_file': return True
    if call.name == 'http_request': return not is_local_url(call.args.get('url'))
    return False


# ----- results ------------------------------------------------------------------------------------------------------------
@dataclass
class ToolResult:
    ok: bool
    output: str
    status: str = ''        # short status line, e.g. 'exit 0', 'HTTP 200', 'timeout'


def truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit: return text
    head = int(limit * 0.6); tail = limit - head
    return text[:head] + f'\n… [{len(text) - limit:,} characters omitted] …\n' + text[-tail:]


def _fence_for(text):
    longest = max((len(m.group(0)) for m in re.finditer(r'`{3,}', text)), default=0)
    return '`' * max(3, longest + 1)


def format_results(calls):
    """The automatic follow-up message with every tool result (calls: list of dicts as stored by the window)."""
    parts = ['[Tool results from the app (automatic message, not typed by the user). Use them to continue the user\'s request. '
             'If you need more information use more tool blocks; otherwise give the final answer (file/edit blocks for file changes). '
             'Do not repeat these results back verbatim.]']
    for i, c in enumerate(calls, 1):
        state = c.get('state')
        label = {'done': 'ok', 'error': 'error', 'rejected': 'rejected by the user', 'skipped': 'not run (stopped by the user)'}.get(state, state)
        args = json.dumps(c.get('args') or {}, ensure_ascii=False)
        if len(args) > 400: args = args[:400] + '…'
        out = c.get('output') or ''
        if state == 'rejected': out = out or 'The user rejected this tool call. Do not retry it unless the user asks; continue without it.'
        status = f" ({c['status']})" if c.get('status') else ''
        fence = _fence_for(out)
        parts.append(f'### {i}. {c.get("name")} {args} -> {label}{status}\n{fence}text\n{truncate(out)}\n{fence}')
    return '\n\n'.join(parts)


# ----- sandbox helpers ---------------------------------------------------------------------------------------------------
def _rel_arg(args, key='path', default='.'):
    value = args.get(key, default)
    if value in (None, '', '.', './', '/') and default == '.': return ''
    if not isinstance(value, str): raise core.PathError(tr('مسیر نامعتبر است'))
    return core.clean_rel(value)


def _resolve(root, rel):
    return Path(root).resolve() if not rel else core.safe_path(root, rel)


def _walk(root, base_rel=''):
    """Files under base_rel (posix rel paths, sizes), skipping ignored folders (.git, node_modules, …, .gitignore); includes
    binary files such as images. Never follows symlinks."""
    root = Path(root).resolve(); patterns = core.load_gitignore(root); start = _resolve(root, base_rel)
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root).replace('\\', '/'); rel_dir = '' if rel_dir == '.' else rel_dir
        dirnames[:] = [d for d in sorted(dirnames) if not os.path.islink(os.path.join(dirpath, d))
                       and not core.ignored(f'{rel_dir}/{d}' if rel_dir else d, True, patterns)]
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            if os.path.islink(full): continue
            rel = f'{rel_dir}/{f}' if rel_dir else f
            if _git_ignored(rel, patterns): continue
            try: yield rel, os.path.getsize(full)
            except OSError: continue


def _git_ignored(rel, patterns):
    name = rel.rsplit('/', 1)[-1]
    for pat in patterns:
        if pat.endswith('/'): continue
        p = pat.lstrip('/')
        if ('/' in pat and fnmatch.fnmatch(rel, p)) or ('/' not in pat and fnmatch.fnmatch(name, p)): return True
    return False


def _size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB': return f'{n:.0f}{unit}' if unit == 'B' else f'{n:.1f}{unit}'
        n /= 1024


# ----- read-only tools -----------------------------------------------------------------------------------------------------
def tool_list_dir(root, args, ctx):
    rel = _rel_arg(args); base = _resolve(root, rel)
    if not base.is_dir(): return ToolResult(False, tr('پوشه وجود ندارد: {v0}', v0=rel or "."))
    try: depth = max(1, min(int(args.get('depth') or 2), 6))
    except (TypeError, ValueError): depth = 2
    patterns = core.load_gitignore(root); rootp = Path(root).resolve(); lines = []; count = [0]

    def walk(path, level):
        try: entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        except OSError: lines.append('  ' * level + tr('(خواندن ممکن نشد)')); return
        for e in entries:
            if count[0] >= MAX_LIST_ENTRIES: return
            r = os.path.relpath(e.path, rootp).replace('\\', '/')
            if e.is_symlink(): lines.append('  ' * level + e.name + ' -> (symlink, not followed)'); count[0] += 1; continue
            if e.is_dir():
                skip = core.ignored(r, True, patterns)
                lines.append('  ' * level + e.name + '/' + (' (ignored)' if skip else '')); count[0] += 1
                if not skip and level + 1 < depth: walk(e.path, level + 1)
            else:
                try: size = e.stat().st_size
                except OSError: size = 0
                lines.append('  ' * level + f'{e.name} ({_size(size)})'); count[0] += 1
    walk(base, 0)
    if count[0] >= MAX_LIST_ENTRIES: lines.append(f'… (limited to {MAX_LIST_ENTRIES} entries; list a sub-folder for more)')
    return ToolResult(True, f'{rel or "."}/\n' + ('\n'.join(lines) if lines else '(empty)'), f'{count[0]} entries')


def _glob_match(rel, pattern):
    pattern = pattern.replace('\\', '/')
    while pattern.startswith('./'): pattern = pattern[2:]
    name = rel.rsplit('/', 1)[-1]
    if '/' not in pattern: return fnmatch.fnmatch(name.lower(), pattern.lower())
    if pattern.startswith('**/') and fnmatch.fnmatch(name.lower(), pattern[3:].lower()) and '/' not in pattern[3:]: return True
    return fnmatch.fnmatch(rel.lower(), pattern.lower())


def tool_find_files(root, args, ctx):
    pattern = str(args.get('pattern') or '*').strip()
    rel = _rel_arg(args); found = []
    if not _resolve(root, rel).is_dir(): return ToolResult(False, tr('پوشه وجود ندارد: {v0}', v0=rel or "."))
    for r, size in _walk(root, rel):
        if ctx.cancelled(): break
        if _glob_match(r, pattern): found.append(f'{r} ({_size(size)})')
        if len(found) >= MAX_LIST_ENTRIES: found.append('… (more matches not listed)'); break
    return ToolResult(True, '\n'.join(found) if found else tr('هیچ فایلی پیدا نشد (no files matched).'), f'{len(found)} files')


def tool_search(root, args, ctx):
    pattern = str(args.get('pattern') or '')
    if not pattern: return ToolResult(False, tr('pattern خالی است'))
    flags = 0 if args.get('case_sensitive') else re.I
    try: rx = re.compile(pattern if args.get('regex') else re.escape(pattern), flags)
    except re.error as e: return ToolResult(False, tr('regex نامعتبر: {e}', e=e))
    glob = str(args.get('glob') or '').strip(); rel = _rel_arg(args); out = []; files = 0; rootp = Path(root).resolve()
    for r, size in _walk(root, rel):
        if ctx.cancelled(): break
        if os.path.splitext(r)[1].lower() in core.BINARY_EXT or size > MAX_SEARCH_FILE_BYTES: continue
        if glob and not _glob_match(r, glob): continue
        try: text = core.read_text(rootp / r).text
        except (OSError, UnicodeError): continue
        hit = False
        for n, line in enumerate(text.split('\n'), 1):
            if rx.search(line):
                hit = True; out.append(f'{r}:{n}: {line.strip()[:300]}')
                if len(out) >= MAX_SEARCH_MATCHES: break
        files += hit
        if len(out) >= MAX_SEARCH_MATCHES: out.append(f'… (limited to {MAX_SEARCH_MATCHES} matches)'); break
    return ToolResult(True, '\n'.join(out) if out else tr('چیزی پیدا نشد (no matches).'), f'{len(out)} matches in {files} files')


def tool_read_file(root, args, ctx):
    rel = _rel_arg(args, default='')
    if not rel: return ToolResult(False, tr('path لازم است'))
    path = core.safe_path(root, rel); pending = ''
    if rel in ctx.overlay:
        if ctx.overlay[rel] is None: return ToolResult(False, tr('{rel} در تغییرات پیشنهادیِ در انتظار بررسی حذف شده است.', rel=rel))
        text = ctx.overlay[rel]; pending = ' [PROPOSED version: includes your pending, not yet applied changes]'
        return _numbered(rel, text, args, pending)
    if not path.is_file(): return ToolResult(False, tr('فایل وجود ندارد: {rel}', rel=rel))
    if path.suffix.lower() in IMAGE_EXT - {'.svg'}: return ToolResult(False, tr('{rel} یک تصویر است؛ از image_info استفاده کنید.', rel=rel))
    if path.stat().st_size > 5_000_000: return ToolResult(False, tr('فایل خیلی بزرگ است ({v0}); از search استفاده کنید.', v0=_size(path.stat().st_size)))
    try: text = core.read_text(path).text
    except UnicodeError: return ToolResult(False, tr('{rel} فایل متنی UTF-8 نیست (باینری یا کدگذاری دیگر).', rel=rel))
    return _numbered(rel, text, args, pending)


def _numbered(rel, text, args, pending=''):
    lines = text.split('\n')
    if lines and lines[-1] == '': lines.pop()
    try: start = max(1, int(args.get('start_line') or 1))
    except (TypeError, ValueError): start = 1
    try: end = min(len(lines), int(args.get('end_line') or len(lines)))
    except (TypeError, ValueError): end = len(lines)
    width = len(str(max(end, 1))); out = []; chars = 0; last = start - 1
    for n in range(start, end + 1):
        row = f'{n:>{width}}| {lines[n - 1]}'
        if chars + len(row) > MAX_READ_CHARS and out: break
        out.append(row); chars += len(row) + 1; last = n
    note = f'{rel} — lines {start}-{last} of {len(lines)}{pending}'
    if last < len(lines): note += f' (call read_file again with "start_line": {last + 1} for more)'
    return ToolResult(True, note + '\n' + '\n'.join(out), f'{last - start + 1} lines')


def tool_count_lines(root, args, ctx):
    rels = []
    if args.get('path'):
        rel = _rel_arg(args, default='')
        base = _resolve(root, rel)
        rels = [r for r, _ in _walk(root, rel)] if base.is_dir() else [rel]
    else:
        glob = str(args.get('glob') or '*'); rels = [r for r, _ in _walk(root) if _glob_match(r, glob)]
    out = []; total = 0
    for rel in rels[:500]:
        if rel in ctx.overlay:
            text = ctx.overlay[rel]
            if text is None: continue
        else:
            p = core.safe_path(root, rel)
            if p.suffix.lower() in core.BINARY_EXT or not p.is_file(): continue
            try: text = core.read_text(p).text
            except (OSError, UnicodeError): continue
        n = len(text.split('\n')) - (1 if text.endswith('\n') else 0) if text else 0
        total += n; out.append(f'{n:>7}  {rel}')
    if not out: return ToolResult(False, tr('هیچ فایل متنی پیدا نشد'))
    return ToolResult(True, '\n'.join(out) + f'\n{total:>7}  total ({len(out)} files)', f'{total} lines')


def image_meta(data, name=''):
    """{'format','width','height'} from the image header (PNG, JPEG, GIF, WebP, BMP, ICO, SVG); {} if unknown."""
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR':
            w, h = struct.unpack('>II', data[16:24]); return {'format': 'PNG', 'width': w, 'height': h}
        if data[:6] in (b'GIF87a', b'GIF89a'):
            w, h = struct.unpack('<HH', data[6:10]); return {'format': 'GIF', 'width': w, 'height': h}
        if data[:2] == b'BM':
            w, h = struct.unpack('<ii', data[18:26]); return {'format': 'BMP', 'width': w, 'height': abs(h)}
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            chunk = data[12:16]
            if chunk == b'VP8X': return {'format': 'WebP', 'width': 1 + int.from_bytes(data[24:27], 'little'), 'height': 1 + int.from_bytes(data[27:30], 'little')}
            if chunk == b'VP8L':
                b = int.from_bytes(data[21:25], 'little'); return {'format': 'WebP', 'width': (b & 0x3FFF) + 1, 'height': ((b >> 14) & 0x3FFF) + 1}
            if chunk == b'VP8 ':
                w, h = struct.unpack('<HH', data[26:30]); return {'format': 'WebP', 'width': w & 0x3FFF, 'height': h & 0x3FFF}
            return {'format': 'WebP'}
        if data[:4] == b'\x00\x00\x01\x00':
            w, h = data[6] or 256, data[7] or 256; return {'format': 'ICO', 'width': w, 'height': h, 'images': struct.unpack('<H', data[4:6])[0]}
        if data[:2] == b'\xff\xd8':
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF: i += 1; continue
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7: i += 2; continue
                length = struct.unpack('>H', data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack('>HH', data[i + 5:i + 9]); return {'format': 'JPEG', 'width': w, 'height': h, 'progressive': marker == 0xC2}
                i += 2 + length
            return {'format': 'JPEG'}
        head = data[:4096].decode('utf-8', 'ignore')
        if '<svg' in head:
            meta = {'format': 'SVG'}
            tag = re.search(r'<svg\b[^>]*>', head, re.S)
            if tag:
                for key in ('width', 'height', 'viewBox'):
                    m = re.search(rf'\b{key}\s*=\s*["\']([^"\']+)["\']', tag.group(0))
                    if m: meta[key] = m.group(1)
            return meta
    except (struct.error, IndexError):
        pass
    return {}


def tool_image_info(root, args, ctx):
    rel = _rel_arg(args, default='')
    if not rel: return ToolResult(False, tr('path لازم است'))
    path = core.safe_path(root, rel)
    if not path.is_file(): return ToolResult(False, tr('فایل وجود ندارد: {rel}', rel=rel))
    size = path.stat().st_size
    with open(path, 'rb') as fh: data = fh.read(min(size, 2_000_000))
    meta = image_meta(data, rel)
    if not meta: return ToolResult(False, tr('{rel}: قالب تصویر شناخته نشد ({v0})', rel=rel, v0=_size(size)))
    lines = [f'path: {rel}', f'format: {meta["format"]}', f'file size: {_size(size)} ({size:,} bytes)']
    if 'width' in meta: lines.append(f'dimensions: {meta["width"]} x {meta["height"]} px')
    for key in ('viewBox', 'progressive', 'images'):
        if key in meta: lines.append(f'{key}: {meta[key]}')
    lines.append('(the image itself is not sent to the model; only this metadata)')
    return ToolResult(True, '\n'.join(lines), f'{meta["format"]} {meta.get("width", "?")}x{meta.get("height", "?")}')


# ----- tools that need approval ----------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


def _http_url(url):
    url = str(url or '').strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname: raise ValueError(tr('فقط نشانی http یا https معتبر پذیرفته می‌شود'))
    return url


def tool_http_request(root, args, ctx):
    try: url = _http_url(args.get('url'))
    except ValueError as e: return ToolResult(False, str(e))
    method = str(args.get('method') or 'GET').upper()
    if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'): return ToolResult(False, tr('متد نامعتبر: {method}', method=method))
    headers = {str(k): str(v) for k, v in (args.get('headers') or {}).items()} if isinstance(args.get('headers'), dict) else {}
    data = None
    if args.get('json') is not None:
        data = json.dumps(args['json'], ensure_ascii=False).encode('utf-8'); headers.setdefault('Content-Type', 'application/json')
    elif args.get('body') is not None:
        data = (args['body'] if isinstance(args['body'], str) else json.dumps(args['body'], ensure_ascii=False)).encode('utf-8')
    headers.setdefault('User-Agent', 'DeepSeekDesktop-ProjectTools/1.0')
    try: timeout = max(1, min(float(args.get('timeout') or HTTP_TIMEOUT), 120))
    except (TypeError, ValueError): timeout = HTTP_TIMEOUT
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    started = time.monotonic()
    try: resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e: resp = e
    except (urllib.error.URLError, OSError, ValueError) as e:
        return ToolResult(False, tr('درخواست ناموفق بود: {v0}', v0=getattr(e, "reason", e)), 'network error')
    with resp:
        body = resp.read(MAX_HTTP_BYTES + 1) if method != 'HEAD' else b''
        status = getattr(resp, 'status', None) or resp.getcode(); reason = getattr(resp, 'reason', '') or ''
        hdrs = resp.headers
    elapsed = time.monotonic() - started
    lines = [f'HTTP {status} {reason}  ({elapsed * 1000:.0f} ms, {len(body[:MAX_HTTP_BYTES]):,} bytes' + (', truncated' if len(body) > MAX_HTTP_BYTES else '') + ')']
    for key in ('Content-Type', 'Content-Length', 'Location', 'Cache-Control', 'Access-Control-Allow-Origin', 'Server', 'Content-Encoding'):
        if hdrs.get(key): lines.append(f'{key}: {hdrs.get(key)}')
    if hdrs.get('Set-Cookie'): lines.append('Set-Cookie: (hidden)')
    body = body[:MAX_HTTP_BYTES]; ctype = (hdrs.get('Content-Type') or '').lower()
    if body:
        meta = image_meta(body) if 'image' in ctype or not ctype else {}
        if meta: lines.append(f'\n(image: {meta.get("format")} {meta.get("width", "?")}x{meta.get("height", "?")})')
        else:
            try: text = body.decode('utf-8')
            except UnicodeDecodeError: text = None
            if text is None or '\x00' in text[:2000]: lines.append(f'\n(binary body, {len(body):,} bytes, {ctype or "unknown type"})')
            else:
                if 'json' in ctype or text.lstrip()[:1] in ('{', '['):
                    try: text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                    except ValueError: pass
                lines.append('\n' + text)
    return ToolResult(200 <= int(status) < 400, truncate('\n'.join(lines)), f'HTTP {status}')


def _download_target(root, args):
    rel = args.get('path')
    if not rel:
        name = PurePosixPath(urllib.parse.unquote(urllib.parse.urlsplit(str(args.get('url'))).path)).name or 'download'
        rel = 'downloads/' + re.sub(r'[<>:"|?*\\]', '_', name)
    rel = core.clean_rel(str(rel))
    return rel, core.safe_path(root, rel)


def tool_download_file(root, args, ctx):
    try: url = _http_url(args.get('url'))
    except ValueError as e: return ToolResult(False, str(e))
    rel, target = _download_target(root, args)
    if target.exists() and not args.get('overwrite'): return ToolResult(False, tr('{rel} از قبل وجود دارد؛ بازنویسی نشد (برای بازنویسی "overwrite": true).', rel=rel))
    if target.exists() and target.is_dir(): return ToolResult(False, tr('{rel} یک پوشه است', rel=rel))
    target.parent.mkdir(parents=True, exist_ok=True)
    core.safe_path(root, rel)   # re-check after creating folders (junction/symlink races)
    tmp = target.with_name(target.name + '.part'); total = 0
    req = urllib.request.Request(url, headers={'User-Agent': 'DeepSeekDesktop-ProjectTools/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp, open(tmp, 'wb') as fh:
            ctype = resp.headers.get('Content-Type') or ''
            while True:
                if ctx.cancelled(): raise InterruptedError('cancelled')
                chunk = resp.read(65536)
                if not chunk: break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES: raise ValueError(tr('فایل بزرگ‌تر از {v0} است', v0=_size(MAX_DOWNLOAD_BYTES)))
                fh.write(chunk)
        os.replace(tmp, target)
    except InterruptedError:
        tmp.unlink(missing_ok=True); return ToolResult(False, tr('دانلود متوقف شد'), 'killed')
    except (urllib.error.URLError, OSError, ValueError) as e:
        tmp.unlink(missing_ok=True); return ToolResult(False, tr('دانلود ناموفق بود: {v0}', v0=getattr(e, "reason", e)), 'error')
    lines = [f'saved: {rel}', f'size: {_size(total)} ({total:,} bytes)', f'content-type: {ctype or "unknown"}']
    with open(target, 'rb') as fh: meta = image_meta(fh.read(2_000_000))
    if meta: lines.append(f'image: {meta.get("format")} {meta.get("width", "?")}x{meta.get("height", "?")}')
    return ToolResult(True, '\n'.join(lines), _size(total))


def command_argv(command, shell=None):
    if os.name == 'nt':
        if str(shell or '').lower() == 'cmd': return ['cmd.exe', '/d', '/s', '/c', command]
        # exit code: the native program's $LASTEXITCODE, or 1 when the last PowerShell statement failed
        return ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                '[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $OutputEncoding=[System.Text.Encoding]::UTF8; '
                '$ProgressPreference="SilentlyContinue"; $global:LASTEXITCODE=0\n' + command +
                '\n$__ok=$?; if ($global:LASTEXITCODE) { exit $global:LASTEXITCODE }; if (-not $__ok) { exit 1 }']
    return ['/bin/bash', '-c', command]


def _decode(data):
    try: return data.decode('utf-8')
    except UnicodeDecodeError:
        for enc in (('oem', 'mbcs') if os.name == 'nt' else ()):
            try: return data.decode(enc)
            except (UnicodeDecodeError, LookupError): pass
        return data.decode('utf-8', 'replace')


def _kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try: proc.kill()
    except OSError: pass


def tool_run_command(root, args, ctx):
    command = str(args.get('command') or '').strip()
    if not command: return ToolResult(False, tr('command خالی است'))
    try: timeout = max(1, min(float(args.get('timeout') or ctx.command_timeout), MAX_COMMAND_TIMEOUT))
    except (TypeError, ValueError): timeout = ctx.command_timeout
    kwargs = dict(cwd=str(Path(root).resolve()), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1'))
    if os.name == 'nt': kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    else: kwargs['start_new_session'] = True
    started = time.monotonic()
    try: proc = subprocess.Popen(command_argv(command, args.get('shell')), **kwargs)
    except OSError as e: return ToolResult(False, tr('اجرای فرمان ممکن نشد: {e}', e=e), 'error')
    buf = bytearray(); limit = MAX_OUTPUT_CHARS * 4

    def pump():
        for chunk in iter(lambda: proc.stdout.read1(4096) if hasattr(proc.stdout, 'read1') else proc.stdout.read(4096), b''):
            buf.extend(chunk)
            if len(buf) > limit * 2: del buf[limit // 2: len(buf) - limit // 2]   # keep head and tail
    reader = threading.Thread(target=pump, daemon=True); reader.start()
    state = ''
    while proc.poll() is None:
        if ctx.cancelled(): state = 'killed'; _kill_tree(proc); break
        if time.monotonic() - started > timeout: state = 'timeout'; _kill_tree(proc); break
        time.sleep(0.05)
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: pass
    reader.join(timeout=3)
    elapsed = time.monotonic() - started; out = _decode(bytes(buf)).replace('\r\n', '\n')
    if state == 'timeout': head = f'TIMEOUT after {timeout:.0f} s: the command was stopped.'
    elif state == 'killed': head = 'Stopped by the user (killed).'
    else: head = f'exit code: {proc.returncode}'
    text = f'$ {command}\n{head}  ({elapsed:.1f} s)\n\n' + (truncate(out.rstrip()) if out.strip() else '(no output)')
    return ToolResult(state == '' and proc.returncode == 0, text, state or f'exit {proc.returncode}')


# ----- dispatcher ---------------------------------------------------------------------------------------------------------
class Context:
    def __init__(self, cancel=None, command_timeout=COMMAND_TIMEOUT, overlay=None):
        self.cancel = cancel or threading.Event(); self.command_timeout = command_timeout
        self.overlay = overlay or {}      # {rel: proposed text or None (deleted)} of changes waiting for review

    def cancelled(self):
        return self.cancel.is_set()


HANDLERS = {'list_dir': tool_list_dir, 'find_files': tool_find_files, 'search': tool_search, 'read_file': tool_read_file,
            'image_info': tool_image_info, 'http_request': tool_http_request, 'download_file': tool_download_file,
            'run_command': tool_run_command, 'count_lines': tool_count_lines}


def is_edit_tool(name):
    return name in EDIT_TOOLS


def execute(name, args, root, ctx=None):
    """Run one tool. Never raises: errors become a failed ToolResult with a (Persian) message."""
    ctx = ctx or Context()
    if name in EDIT_TOOLS: return ToolResult(False, tr('ابزارهای ویرایش در پنل بازبینی اجرا می‌شوند'))
    if name not in HANDLERS: return ToolResult(False, tr('ابزار ناشناخته: {name}', name=name))
    if not root or not os.path.isdir(root): return ToolResult(False, tr('پوشهٔ پروژه در دسترس نیست'))
    allowed = TOOLS[name][1]
    unknown = [k for k in (args or {}) if k not in allowed]
    try:
        result = HANDLERS[name](root, {k: v for k, v in (args or {}).items() if k in allowed}, ctx)
    except core.PathError as e:
        return ToolResult(False, tr('مسیر رد شد: {e}', e=e), 'blocked')
    except Exception as e:   # pragma: no cover - defensive
        return ToolResult(False, tr('خطای ابزار: {name__}: {e}', name__=type(e).__name__, e=e), 'error')
    if unknown: result.output = f'(ignored unknown arguments: {", ".join(map(str, unknown))})\n' + result.output
    return result
