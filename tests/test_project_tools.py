"""Project-mode agent tools (no Qt): protocol parser, sandbox, approval gating, commands (timeout / kill / truncation),
HTTP requests and downloads against a local test server, image metadata and the results message."""
import http.server, json, os, struct, sys, threading, time
import pytest
from app.project import tools as T


def make_project(tmp_path):
    root = tmp_path / 'proj'; (root / 'src').mkdir(parents=True); (root / 'img').mkdir(); (root / 'node_modules' / 'x').mkdir(parents=True)
    (root / 'src' / 'app.js').write_text('const a = 1;\nfunction hello() {\n  return "سلام";\n}\n', encoding='utf-8')
    (root / 'src' / 'util.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    (root / 'node_modules' / 'x' / 'index.js').write_text('hello()')
    (root / 'secret.log').write_text('hello secret'); (root / '.gitignore').write_text('*.log\n')
    (root / 'img' / 'logo.png').write_bytes(png(64, 32))
    (tmp_path / 'outside.txt').write_text('outside')
    return root


def png(w, h):
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0) + b'\x00' * 20


def jpeg(w, h):
    return b'\xff\xd8' + b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9 + b'\xff\xc0' + struct.pack('>HBHHB', 11, 8, h, w, 3) + b'\x00' * 9 + b'\xff\xd9'


def run(name, args, root, **kw):
    return T.execute(name, args, str(root), T.Context(**kw))


# ----- parser -----------------------------------------------------------------------------------------------------------------
def test_parse_json_plain_kv_alias_and_unknown():
    text = ('اول ساختار را می‌بینم.\n\n```tool:list_dir\n{"path": "src", "depth": 3}\n```\n\n```tool:read_file\nsrc/app.js\n```\n\n'
            '```tool:grep\npattern: hello\nglob: *.js\n```\n\n```tool:run_command\nnpm test -- --watch=false\n```\n\n'
            '```tool:format_disk\n{}\n```\n\n```file:src/a.txt\nnot a tool\n```\n')
    calls = T.parse_calls(text)
    assert [(c.name, c.args, c.error) for c in calls[:4]] == [
        ('list_dir', {'path': 'src', 'depth': 3}, ''), ('read_file', {'path': 'src/app.js'}, ''),
        ('search', {'pattern': 'hello', 'glob': '*.js'}, ''), ('run_command', {'command': 'npm test -- --watch=false'}, '')]
    assert calls[4].error.startswith('ابزار ناشناخته') and len(calls) == 5


def test_parse_streamed_partial_and_bad_json_and_long_fence():
    partial = 'باشه\n```tool:run_command\n{"command": "npm'
    assert T.parse_calls(partial, final=False)[0].complete is False and T.parse_calls(partial, final=False)[0].error == ''
    assert T.parse_calls(partial, final=True)[0].error == 'بلوک ابزار ناتمام ماند'
    assert 'JSON' in T.parse_calls('```tool:read_file\n{"path": \n```')[0].error
    four = T.parse_calls('````tool:run_command\n{"command": "echo ```"}\n````')
    assert four[0].args == {'command': 'echo ```'} and four[0].complete
    assert T.parse_calls('سلام! چطور می‌تونم کمک کنم؟') == []
    win = T.parse_calls('```tool:run_command\n{"command": "dir C:\\Users\\me\\proj\\src"}\n```')[0]   # unescaped backslashes
    assert win.error == '' and win.args == {'command': 'dir C:\\Users\\me\\proj\\src'}


# ----- sandbox ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('name,args', [('read_file', {'path': '../outside.txt'}), ('read_file', {'path': '/etc/passwd'}),
                                        ('read_file', {'path': 'C:/Windows/win.ini'}), ('list_dir', {'path': '..'}),
                                        ('image_info', {'path': '..\\outside.txt'}), ('search', {'pattern': 'x', 'path': '../'}),
                                        ('download_file', {'url': 'http://127.0.0.1:9/x', 'path': '../evil.txt'})])
def test_paths_outside_project_are_blocked(tmp_path, name, args):
    root = make_project(tmp_path)
    result = run(name, args, root)
    assert not result.ok and result.status == 'blocked' and 'outside' not in result.output.split('\n')[-1].replace('outside.txt', '')
    assert not (tmp_path / 'evil.txt').exists()


@pytest.mark.skipif(os.name == 'nt', reason='symlinks need admin rights on Windows')
def test_symlink_escape_is_blocked(tmp_path):
    root = make_project(tmp_path); (root / 'link').symlink_to(tmp_path)
    assert run('read_file', {'path': 'link/outside.txt'}, root).status == 'blocked'
    assert 'symlink' in run('list_dir', {}, root).output


def test_list_find_search_read(tmp_path):
    root = make_project(tmp_path)
    listing = run('list_dir', {'depth': 3}, root).output
    assert 'src/' in listing and 'app.js' in listing and 'node_modules/ (ignored)' in listing and 'index.js' not in listing
    found = run('find_files', {'pattern': '*.png'}, root)
    assert found.ok and 'img/logo.png' in found.output
    assert 'src/app.js' in run('find_files', {'pattern': 'src/**/*.js'}, root).output or 'src/app.js' in run('find_files', {'pattern': 'src/*.js'}, root).output
    grep = run('search', {'pattern': 'hello'}, root).output
    assert 'src/app.js:2:' in grep and 'node_modules' not in grep and 'secret.log' not in grep     # ignored dir and .gitignore
    assert 'src/app.js:3:' in run('search', {'pattern': r'return\s+"', 'regex': True}, root).output
    assert not run('search', {'pattern': '(', 'regex': True}, root).ok
    read = run('read_file', {'path': 'src/app.js', 'start_line': 2, 'end_line': 3}, root).output
    assert '2| function hello() {' in read and '3|   return "سلام";' in read and '1| const' not in read
    assert not run('read_file', {'path': 'img/logo.png'}, root).ok          # images: use image_info


def test_image_info_formats(tmp_path):
    root = make_project(tmp_path)
    (root / 'img' / 'p.jpg').write_bytes(jpeg(800, 600)); (root / 'img' / 'a.gif').write_bytes(b'GIF89a' + struct.pack('<HH', 10, 20) + b'\x00' * 10)
    (root / 'img' / 'i.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"></svg>')
    assert 'dimensions: 64 x 32 px' in run('image_info', {'path': 'img/logo.png'}, root).output
    assert 'JPEG' in run('image_info', {'path': 'img/p.jpg'}, root).output and '800 x 600' in run('image_info', {'path': 'img/p.jpg'}, root).output
    assert '10 x 20' in run('image_info', {'path': 'img/a.gif'}, root).output
    assert 'viewBox: 0 0 24 24' in run('image_info', {'path': 'img/i.svg'}, root).output
    assert not run('image_info', {'path': 'src/app.js'}, root).ok


# ----- approval gating ---------------------------------------------------------------------------------------------------
def call(name, **args):
    return T.ToolCall(name, args)


def test_needs_approval():
    for name, args in [('list_dir', {}), ('find_files', {'pattern': '*'}), ('search', {'pattern': 'x'}), ('read_file', {'path': 'a'}),
                       ('image_info', {'path': 'a.png'}), ('http_request', {'url': 'http://localhost:3000/api'}),
                       ('http_request', {'url': 'http://127.0.0.1:8000'}), ('http_request', {'url': 'http://[::1]:5000/'})]:
        assert not T.needs_approval(call(name, **args)), name
    for name, args in [('run_command', {'command': 'dir'}), ('download_file', {'url': 'http://localhost/x.png'}),
                       ('http_request', {'url': 'https://api.example.com/v1'}), ('http_request', {'url': 'http://localhost.evil.com/'}),
                       ('http_request', {'url': 'http://10.0.0.5/'})]:
        assert T.needs_approval(call(name, **args)), name
    ro = lambda c: not T.needs_approval(call('run_command', command=c), allow_readonly_commands=True)
    assert ro('git status') and ro('dir src') and ro('Get-ChildItem -Recurse | Select-Object Name') and ro('node --version') and ro('git log -5')
    for bad in ['del app.js', 'rm -rf src', 'dir > out.txt', 'type ..\\secret.txt', 'Get-Content C:\\Users\\x\\a.txt', 'echo $env:TOKEN',
                'git status; del a', 'git push', 'git branch -D main', 'npm install', 'cat a | Set-Content b', 'Remove-Item a', 'python -c "x"',
                'dir & del a', 'git diff --output=x.txt', 'type %USERPROFILE%\\a']:
        assert not ro(bad), bad


# ----- run_command ---------------------------------------------------------------------------------------------------------
def py(code):
    exe = sys.executable
    return (f'& "{exe}" -c "{code}"' if os.name == 'nt' else f'"{exe}" -c "{code}"')


def test_run_command_output_exit_code_and_cwd(tmp_path):
    root = make_project(tmp_path)
    res = run('run_command', {'command': py('import os; print(os.getcwd()); print(chr(1587)+chr(1604)+chr(1575)+chr(1605))')}, root)
    assert res.ok and res.status == 'exit 0' and os.path.realpath(str(root)).lower() in res.output.lower().replace('\\\\', '\\') and 'سلام' in res.output
    bad = run('run_command', {'command': py('import sys; sys.exit(3)')}, root)
    assert not bad.ok and bad.status == 'exit 3' and 'exit code: 3' in bad.output


def test_run_command_timeout_and_truncation(tmp_path):
    root = make_project(tmp_path); started = time.monotonic()
    res = run('run_command', {'command': py('import time; print(1, flush=True); time.sleep(60)'), 'timeout': 2}, root)
    assert res.status == 'timeout' and not res.ok and 'TIMEOUT after 2 s' in res.output and time.monotonic() - started < 30
    big = run('run_command', {'command': py("print('x' * 60000)")}, root)
    assert big.ok and 'characters omitted' in big.output and len(big.output) < T.MAX_OUTPUT_CHARS + 500


def test_run_command_kill(tmp_path):
    root = make_project(tmp_path); cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start(); started = time.monotonic()
    res = T.execute('run_command', {'command': py('import time; time.sleep(60)')}, str(root), T.Context(cancel))
    assert res.status == 'killed' and 'killed' in res.output and time.monotonic() - started < 30


# ----- HTTP / download against a local server ---------------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == '/api/items':
            body = json.dumps({'items': [1, 2], 'name': 'سلام'}).encode(); self.send_response(200); self.send_header('Content-Type', 'application/json')
        elif self.path == '/logo.png':
            body = png(120, 80); self.send_response(200); self.send_header('Content-Type', 'image/png')
        elif self.path == '/old':
            body = b''; self.send_response(302); self.send_header('Location', 'http://example.com/new')
        else:
            body = b'not found'; self.send_response(404); self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body))); self.send_header('Set-Cookie', 'sid=SECRET'); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length'])); self.send_response(201); self.send_header('Content-Type', 'application/json')
        self.end_headers(); self.wfile.write(json.dumps({'got': json.loads(data), 'ctype': self.headers['Content-Type']}).encode())


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler); t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown(); srv.server_close()


def test_http_request(tmp_path, server):
    root = make_project(tmp_path)
    ok = run('http_request', {'url': server + '/api/items'}, root)
    assert ok.ok and ok.status == 'HTTP 200' and '"items": [' in ok.output and 'سلام' in ok.output and 'SECRET' not in ok.output
    assert run('http_request', {'url': server + '/missing'}, root).status == 'HTTP 404'
    redirect = run('http_request', {'url': server + '/old'}, root)
    assert redirect.status == 'HTTP 302' and 'Location: http://example.com/new' in redirect.output   # not followed
    post = run('http_request', {'method': 'POST', 'url': server + '/x', 'json': {'a': 1}}, root)
    assert post.status == 'HTTP 201' and '"a": 1' in post.output and 'application/json' in post.output
    assert not run('http_request', {'url': 'file:///etc/passwd'}, root).ok


def test_download_file(tmp_path, server):
    root = make_project(tmp_path)
    res = run('download_file', {'url': server + '/logo.png', 'path': 'assets/logo.png'}, root)
    assert res.ok and (root / 'assets' / 'logo.png').read_bytes() == png(120, 80) and '120x80' in res.output
    again = run('download_file', {'url': server + '/logo.png', 'path': 'assets/logo.png'}, root)
    assert not again.ok and 'وجود دارد' in again.output
    default = run('download_file', {'url': server + '/logo.png'}, root)
    assert default.ok and (root / 'downloads' / 'logo.png').exists()
    assert run('download_file', {'url': server + '/logo.png', 'path': '.git/hooks/x'}, root).status == 'blocked'


def test_format_results():
    calls = [{'name': 'read_file', 'args': {'path': 'a.md'}, 'state': 'done', 'output': 'text with ``` fence', 'status': '3 lines'},
             {'name': 'run_command', 'args': {'command': 'rm -rf /'}, 'state': 'rejected', 'output': ''},
             {'name': 'run_command', 'args': {'command': 'npm test'}, 'state': 'skipped', 'output': ''}]
    text = T.format_results(calls)
    assert text.startswith('[Tool results from the app') and '````text\ntext with ``` fence\n````' in text
    assert 'rejected by the user' in text and 'The user rejected this tool call' in text and 'not run (stopped by the user)' in text
    assert T.truncate('a' * 50000).count('characters omitted') == 1
