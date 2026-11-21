"""Structured edit tools: line-range moves across files, encoding/BOM/CRLF preservation, Persian text, markers,
regex replace over a glob, path rename with import updates (JS/TS, Python, CSS/HTML, PHP, Java, Go), patches,
sandbox escapes, apply + undo through the normal review flow."""
import os
import pytest
from app.project import core, edits, tools as T


def plan(root, reply, base=()):
    ops = core.parse_ops(reply)
    calls = [c for c in T.parse_calls(reply) if T.is_edit_tool(c.name)]
    return edits.plan_turn(root, ops, [(c.pos, c.name, c.args, c.error) for c in calls], base)


def by_path(changes):
    return {c.path: c for c in changes}


def apply(root, changes, tmp_path):
    return core.apply_changes(root, changes, tmp_path / 'hist')


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / 'p'; (root / 'src').mkdir(parents=True)
    (root / 'src' / 'app.js').write_text(
        "import { a } from './util';\n\nfunction total(items) {\n  return items.reduce((s, x) => s + x, 0);\n}\n\n"
        "function main() {\n  console.log(total([1, 2]));\n}\n", encoding='utf-8')
    (tmp_path / 'outside.txt').write_text('x')
    return root


def test_move_lines_to_new_file_and_apply_undo(proj, tmp_path):
    reply = ('```tool:move_lines\n{"from": "src/app.js", "start": 3, "end": 5, "start_marker": "function total", "end_marker": "}", '
             '"to": "src/lib/total.js", "position": "end"}\n```\n'
             '```tool:insert_text\n{"path": "src/app.js", "after": "import { a }", "text": "import { total } from \'./lib/total\';"}\n```')
    changes, results = plan(proj, reply)
    assert all(ok for ok, _ in results) and 'moved 3 lines src/app.js:3-5' in results[0][1]
    ch = by_path(changes)
    assert ch['src/lib/total.js'].kind == 'create' and ch['src/lib/total.js'].new == 'function total(items) {\n  return items.reduce((s, x) => s + x, 0);\n}\n'
    assert ch['src/app.js'].new.startswith("import { a } from './util';\nimport { total } from './lib/total';\n\n\nfunction main")
    before = (proj / 'src' / 'app.js').read_bytes()
    apply(proj, changes, tmp_path)
    assert (proj / 'src' / 'lib' / 'total.js').exists() and 'function total' not in (proj / 'src' / 'app.js').read_text()
    core.undo_last(proj, tmp_path / 'hist')
    assert (proj / 'src' / 'app.js').read_bytes() == before and not (proj / 'src' / 'lib' / 'total.js').exists()


def test_markers_relocate_stale_numbers_and_reject_mismatch(proj):
    ok = plan(proj, '```tool:delete_lines\n{"path": "src/app.js", "start": 4, "end": 6, "start_marker": "function total", "end_marker": "}"}\n```')
    assert ok[1][0][0] and 'جابه‌جا شد' in ok[1][0][1] and 'function total' not in by_path(ok[0])['src/app.js'].new
    bad = plan(proj, '```tool:delete_lines\n{"path": "src/app.js", "start": 3, "end": 4, "end_marker": "}"}\n```')
    assert not bad[1][0][0] and 'end_marker' in bad[1][0][1] and bad[0] == []
    amb = plan(proj, '```tool:delete_lines\n{"path": "src/app.js", "start_marker": "function"}\n```')
    assert not amb[1][0][0] and 'مبهم' in amb[1][0][1]


def test_crlf_bom_persian_preserved_across_files(tmp_path):
    root = tmp_path / 'r'; root.mkdir()
    (root / 'a.txt').write_bytes('\ufeffسطر یک\r\nسطر دو\r\nسطر سه\r\n'.encode('utf-8'))
    (root / 'b.txt').write_bytes('first\nsecond\n'.encode('utf-8'))
    changes, res = plan(root, '```tool:move_lines\n{"from": "a.txt", "start": 2, "end": 2, "to": "b.txt", "after": "first"}\n```\n'
                              '```tool:copy_lines\n{"from": "a.txt", "start": 1, "end": 1, "to": "c.txt"}\n```')
    assert all(ok for ok, _ in res)
    core.apply_changes(root, changes, tmp_path / 'h')
    assert (root / 'a.txt').read_bytes() == '\ufeffسطر یک\r\nسطر سه\r\n'.encode('utf-8')           # BOM + CRLF kept
    assert (root / 'b.txt').read_bytes() == 'first\nسطر دو\nsecond\n'.encode('utf-8')             # LF file stays LF
    assert (root / 'c.txt').read_bytes() == '\ufeffسطر یک\r\n'.encode('utf-8')                     # new file inherits source style


def test_same_file_move_indent_and_replace_lines(tmp_path):
    root = tmp_path / 'r'; root.mkdir()
    (root / 'm.py').write_text('def a():\n    pass\n\nclass K:\n    x = 1\n', encoding='utf-8')
    changes, res = plan(root, '```tool:move_lines\n{"from": "m.py", "start": 1, "end": 2, "to": "m.py", "position": "end", "indent": 4}\n```\n'
                              '```tool:replace_lines\n{"path": "m.py", "start_marker": "x = 1", "text": "    x = 2\\n    y = 3"}\n```')
    assert all(ok for ok, _ in res), res
    assert by_path(changes)['m.py'].new == '\nclass K:\n    x = 2\n    y = 3\n    def a():\n        pass\n'


def test_json_header_with_raw_text_body(tmp_path):
    root = tmp_path / 'r'; root.mkdir(); (root / 'a.js').write_text('const x = 1;\n')
    changes, res = plan(root, '```tool:insert_text\n{"path": "a.js", "position": "end"}\nfunction f() {\n  return "\\"q\\"";\n}\n```')
    assert res[0][0] and by_path(changes)['a.js'].new == 'const x = 1;\nfunction f() {\n  return "\\"q\\"";\n}\n'


def test_replace_text_regex_multi_file_with_safeguards(tmp_path):
    root = tmp_path / 'r'; (root / 'src').mkdir(parents=True); (root / 'node_modules').mkdir()
    (root / 'src' / 'a.ts').write_text('getUser(1); getUser(2);\n'); (root / 'src' / 'b.ts').write_text('x = getUser(3)\n')
    (root / 'src' / 'c.md').write_text('getUser(9)\n'); (root / 'node_modules' / 'd.ts').write_text('getUser(0)\n')
    dry = plan(root, '```tool:replace_text\n{"pattern": "getUser\\\\((\\\\d)\\\\)", "replacement": "fetchUser($1)", "glob": "**/*.ts", "regex": true, "dry_run": true}\n```')
    assert dry[0] == [] and '3 matches in 2 files' in dry[1][0][1]
    wrong = plan(root, '```tool:replace_text\n{"pattern": "getUser", "replacement": "fetchUser", "glob": "*.ts", "expected_count": 5}\n```')
    assert not wrong[1][0][0] and 'expected_count=5' in wrong[1][0][1] and wrong[0] == []
    changes, res = plan(root, '```tool:replace_text\n{"pattern": "getUser\\\\((\\\\d)\\\\)", "replacement": "fetchUser($1)", "glob": "**/*.ts", "regex": true, "expected_count": 3}\n```')
    ch = by_path(changes)
    assert res[0][0] and set(ch) == {'src/a.ts', 'src/b.ts'} and ch['src/a.ts'].new == 'fetchUser(1); fetchUser(2);\n'


def test_rename_with_js_css_html_python_updates(tmp_path):
    root = tmp_path / 'r'
    for rel, text in {
        'src/utils/format.ts': "export const f = 1;\n",
        'src/app.tsx': "import { f } from './utils/format';\nimport s from './styles/main.css';\nconst x = require('./utils/format.ts');\n",
        'src/pages/home.ts': "import { f } from '../utils/format';\n",
        'src/styles/main.css': "@import './base.css';\nbody { background: url(../img/bg.png); }\n",
        'src/styles/base.css': 'html {}\n', 'src/img/bg.png': 'PNG',
        'index.html': '<link href="src/styles/main.css"><script src="src/app.tsx"></script><a href="https://x.com/a.css">',
        'pkg/__init__.py': '', 'pkg/helpers.py': 'def h(): pass\n',
        'main.py': 'import pkg.helpers\nfrom pkg.helpers import h\nfrom pkg import helpers\n',
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(text, encoding='utf-8')
    changes, res = plan(root, '```tool:move_path\n{"from": "src/utils/format.ts", "to": "src/lib/fmt.ts"}\n```\n'
                              '```tool:rename_path\n{"from": "src/styles", "to": "src/css"}\n```\n'
                              '```tool:move_path\n{"from": "pkg/helpers.py", "to": "pkg/util/helpers2.py"}\n```\n'
                              '```tool:make_dir\n{"path": "pkg/util"}\n```')
    assert all(ok for ok, _ in res), res
    ch = by_path(changes)
    assert ch['src/app.tsx'].new == "import { f } from './lib/fmt';\nimport s from './css/main.css';\nconst x = require('./lib/fmt.ts');\n"
    assert ch['src/pages/home.ts'].new == "import { f } from '../lib/fmt';\n"
    assert ch['src/css/main.css'].new == "@import './base.css';\nbody { background: url(../img/bg.png); }\n"   # moved with its folder
    assert ch['index.html'].new == '<link href="src/css/main.css"><script src="src/app.tsx"></script><a href="https://x.com/a.css">'
    assert ch['main.py'].new == 'import pkg.util.helpers2\nfrom pkg.util.helpers2 import h\nfrom pkg.util import helpers2 as helpers\n'
    assert ch['src/utils/format.ts'].kind == 'delete' and ch['src/styles/base.css'].kind == 'delete' and ch['src/lib/fmt.ts'].kind == 'create'
    core.apply_changes(root, changes, tmp_path / 'h')
    assert not (root / 'src' / 'styles').exists() and (root / 'src' / 'css' / 'base.css').exists()     # emptied folder removed
    core.undo_last(root, tmp_path / 'h')
    assert (root / 'src' / 'styles' / 'main.css').exists() and not (root / 'src' / 'css' / 'main.css').exists()


def test_php_java_go_references(tmp_path):
    root = tmp_path / 'r'
    for rel, text in {
        'inc/db.php': '<?php\n', 'index.php': "<?php require_once __DIR__ . '/inc/db.php';\ninclude 'inc/db.php';\n",
        'src/main/java/com/shop/model/Item.java': 'package com.shop.model;\npublic class Item {}\n',
        'src/main/java/com/shop/App.java': 'package com.shop;\nimport com.shop.model.Item;\n',
        'go.mod': 'module example.com/shop\n', 'internal/db/db.go': 'package db\n', 'cmd/main.go': 'import "example.com/shop/internal/db"\n',
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True); (root / rel).write_text(text, encoding='utf-8')
    changes, res = plan(root, '```tool:move_path\n{"from": "inc/db.php", "to": "lib/database.php"}\n```\n'
                              '```tool:move_path\n{"from": "src/main/java/com/shop/model/Item.java", "to": "src/main/java/com/shop/domain/Item.java"}\n```\n'
                              '```tool:move_path\n{"from": "internal/db", "to": "internal/storage"}\n```')
    assert all(ok for ok, _ in res), res
    ch = by_path(changes)
    assert ch['index.php'].new == "<?php require_once __DIR__ . '/lib/database.php';\ninclude 'lib/database.php';\n"
    assert ch['src/main/java/com/shop/domain/Item.java'].new.startswith('package com.shop.domain;')
    assert ch['src/main/java/com/shop/App.java'].new == 'package com.shop;\nimport com.shop.domain.Item;\n'
    assert ch['cmd/main.go'].new == 'import "example.com/shop/internal/storage"\n'


def test_copy_path_binary_and_apply(tmp_path):
    root = tmp_path / 'r'; (root / 'img').mkdir(parents=True); (root / 'img' / 'a.png').write_bytes(b'\x89PNG\x00\x01\x02')
    changes, res = plan(root, '```tool:copy_path\n{"from": "img", "to": "assets/img"}\n```')
    assert res[0][0] and by_path(changes)['assets/img/a.png'].raw == b'\x89PNG\x00\x01\x02'
    core.apply_changes(root, changes, tmp_path / 'h')
    assert (root / 'assets' / 'img' / 'a.png').read_bytes() == b'\x89PNG\x00\x01\x02' and (root / 'img' / 'a.png').exists()
    exists = plan(root, '```tool:copy_path\n{"from": "img/a.png", "to": "assets/img/a.png"}\n```')
    assert not exists[1][0][0] and 'وجود دارد' in exists[1][0][1]


def test_apply_patch_offset_create_and_errors(tmp_path):
    root = tmp_path / 'r'; root.mkdir(); (root / 'a.py').write_text('# header\nx = 1\ny = 2\nz = 3\n', encoding='utf-8')
    patch = ('--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,3 @@\n x = 1\n-y = 2\n+y = 20\n z = 3\n'      # line numbers off by one
             '--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+سلام\n+دنیا\n')
    changes, res = plan(root, '```tool:apply_patch\n' + patch + '```')
    assert res[0][0], res
    ch = by_path(changes)
    assert ch['a.py'].new == '# header\nx = 1\ny = 20\nz = 3\n' and ch['new.txt'].new == 'سلام\nدنیا\n'
    bad = plan(root, '```tool:apply_patch\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-nope\n+x\n```')
    assert not bad[1][0][0] and 'جور نیست' in bad[1][0][1]


@pytest.mark.parametrize('reply', [
    '```tool:move_lines\n{"from": "../outside.txt", "start": 1, "end": 1, "to": "a.txt"}\n```',
    '```tool:copy_lines\n{"from": "src/app.js", "start": 1, "end": 1, "to": "../evil.js"}\n```',
    '```tool:move_path\n{"from": "src", "to": "/tmp/evil"}\n```',
    '```tool:copy_path\n{"from": "src/app.js", "to": "C:/evil.js"}\n```',
    '```tool:make_dir\n{"path": ".git/hooks2"}\n```',
    '```tool:replace_text\n{"pattern": "x", "replacement": "y", "path": "../outside.txt"}\n```',
    '```tool:apply_patch\n--- a/../outside.txt\n+++ b/../outside.txt\n@@ -1 +1 @@\n-x\n+y\n```',
    '```tool:insert_file_content\n{"from": "../outside.txt", "to": "src/a.js"}\n```',
])
def test_edit_sandbox_escapes(proj, tmp_path, reply):
    changes, res = plan(proj, reply)
    assert changes == [] and not res[0][0]
    assert (tmp_path / 'outside.txt').read_text() == 'x' and not (tmp_path / 'evil.js').exists()


def test_session_builds_on_pending_changes(proj):
    first, _ = plan(proj, '```tool:delete_lines\n{"path": "src/app.js", "start": 1, "end": 2}\n```')
    second, res = plan(proj, '```tool:delete_lines\n{"path": "src/app.js", "start_marker": "function main", "end_marker": "}"}\n```', first)
    assert res[0][0] and by_path(second)['src/app.js'].new == 'function total(items) {\n  return items.reduce((s, x) => s + x, 0);\n}\n\n'


def test_read_file_sees_pending_proposal(proj):
    res = T.execute('read_file', {'path': 'src/app.js'}, str(proj), T.Context(overlay={'src/app.js': 'new\n'}))
    assert 'PROPOSED' in res.output and '1| new' in res.output
    assert 'total' in T.execute('count_lines', {'path': 'src'}, str(proj)).output
