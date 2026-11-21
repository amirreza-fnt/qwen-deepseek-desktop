"""Project mode core: path safety, protocol parser (incl. streamed partial), planning, diff, apply and undo."""
import os, sys
import pytest
from app.project import core
from app.project.core import PathError, safe_path, parse_ops, plan_changes, apply_changes, undo_last, find_replace

def make(tmp_path):
    root = tmp_path / 'proj'; (root / 'src').mkdir(parents=True)
    (root / 'src' / 'app.py').write_text('def f():\n    return 1\n\n\ndef g():\n    return 2\n', encoding='utf-8')
    (root / 'README.md').write_bytes(b'\xef\xbb\xbf# Title\r\nline two\r\n')
    return root

@pytest.mark.parametrize('bad', ['/etc/passwd', 'C:/Windows/x.txt', 'c:\\x', '../x', 'src/../../x', 'a/../../b', '\\\\server\\share\\x', '.git/config', '', 'a\x00b', 'con<1>.txt'])
def test_paths_outside_root_rejected(tmp_path, bad):
    root = make(tmp_path)
    with pytest.raises(PathError): safe_path(root, bad)

def test_paths_inside_root_ok(tmp_path):
    root = make(tmp_path)
    assert safe_path(root, 'src/app.py') == (root / 'src' / 'app.py').resolve()
    assert safe_path(root, './src\\new/file.txt') == (root / 'src' / 'new' / 'file.txt').resolve()

@pytest.mark.skipif(sys.platform == 'win32', reason='symlink creation needs privileges on Windows')
def test_symlink_escape_rejected(tmp_path):
    root = make(tmp_path); outside = tmp_path / 'outside'; outside.mkdir()
    os.symlink(outside, root / 'link')
    with pytest.raises(PathError): safe_path(root, 'link/evil.txt')
    files, _ = core.scan(root); assert not any(r.startswith('link') for r, _ in files)

def test_scan_respects_ignores_and_gitignore(tmp_path):
    root = make(tmp_path)
    for d in ('node_modules/x', '.git', 'venv/lib', 'dist', '__pycache__', 'secret'): (root / d).mkdir(parents=True, exist_ok=True)
    (root / 'node_modules' / 'x' / 'i.js').write_text('x'); (root / 'dist' / 'b.js').write_text('x'); (root / 'logo.png').write_bytes(b'\x89PNG')
    (root / 'secret' / 'k.txt').write_text('x'); (root / 'debug.log').write_text('x'); (root / '.gitignore').write_text('secret/\n*.log\n')
    rels = [r for r, _ in core.scan(root)[0]]
    assert sorted(rels) == ['.gitignore', 'README.md', 'src/app.py']
    tree = core.tree_text(core.scan(root)[0]); assert 'src/\n  app.py' in tree

REPLY = '''توضیح فارسی.

```file:src/new_module.py
def hello():
    return "سلام"
```

```edit:src/app.py
<<<<<<< SEARCH
def g():
    return 2
=======
def g():
    return 3
>>>>>>> REPLACE
```

````file:docs/guide.md
# Guide
```python
print(1)
```
````

```delete:README.md
```
پایان.'''

def test_parser_reads_all_block_kinds():
    ops = parse_ops(REPLY)
    assert [(o.kind, o.path, o.complete) for o in ops] == [('write', 'src/new_module.py', True), ('edit', 'src/app.py', True), ('write', 'docs/guide.md', True), ('delete', 'README.md', True)]
    assert ops[0].content == 'def hello():\n    return "سلام"\n' and ops[1].pairs == [('def g():\n    return 2\n', 'def g():\n    return 3\n')]
    assert '```python\nprint(1)\n```' in ops[2].content and not any(o.error for o in ops)

def test_parser_streamed_partial_prefixes():
    for cut in range(0, len(REPLY), 7):
        ops = parse_ops(REPLY[:cut], final=False)
        assert all(o.complete for o in ops[:-1])           # only the last one may still be open
        assert len(ops) <= 4
    ops = parse_ops(REPLY[:REPLY.index('return 3')], final=False)
    assert ops[-1].kind == 'edit' and not ops[-1].complete and ops[-1].pairs == []
    final = parse_ops(REPLY[:REPLY.index('return 3')], final=True)
    assert final[-1].error

def test_parser_rejects_unsafe_path_in_block(tmp_path):
    ops = parse_ops('```file:../evil.txt\nx\n```\n```file:/abs.txt\nx\n```')
    assert all(o.error for o in ops)
    changes = plan_changes(make(tmp_path), ops); assert all(c.state == 'error' for c in changes)
    assert not (tmp_path / 'evil.txt').exists()

def test_find_replace_exact_fuzzy_and_ambiguous():
    text = 'a = 1\nif x:\n    call(a,  b)\n    done()\n'
    assert find_replace(text, 'a = 1\n', 'a = 2\n')[0].startswith('a = 2')
    new, note = find_replace(text, 'if x:\n  call(a, b)\n', 'if x:\n  call(a, c)\n  more()\n')
    assert note and new == 'a = 1\nif x:\n    call(a, c)\n    more()\n    done()\n'
    with pytest.raises(ValueError, match='مبهم'): find_replace('x\nx\n', 'x\n', 'y\n')
    with pytest.raises(ValueError, match='مبهم'): find_replace('  x\n y\n x\n  y\n', 'x\ny', 'z')
    with pytest.raises(ValueError, match='پیدا نشد'): find_replace(text, 'nothing here', 'z')

def test_plan_apply_and_undo_roundtrip(tmp_path):
    root = make(tmp_path); hist = tmp_path / 'hist'
    before = {p: (root / p).read_bytes() for p in ('src/app.py', 'README.md')}
    changes = plan_changes(root, parse_ops(REPLY))
    kinds = {c.path: (c.kind, c.state) for c in changes}
    assert kinds == {'src/new_module.py': ('create', 'pending'), 'src/app.py': ('modify', 'pending'), 'docs/guide.md': ('create', 'pending'), 'README.md': ('delete', 'pending')}
    diff = core.unified_diff(changes[1]); assert '-    return 2' in diff and '+    return 3' in diff and core.diff_stats(changes[1]) == (1, 1)
    entry = apply_changes(root, changes, hist)
    assert entry and (root / 'src' / 'new_module.py').read_text(encoding='utf-8').endswith('"سلام"\n')
    assert 'return 3' in (root / 'src' / 'app.py').read_text() and not (root / 'README.md').exists()
    assert all(c.state == 'applied' for c in changes)
    restored = undo_last(root, hist)
    assert set(restored) == set(kinds) and not (root / 'src' / 'new_module.py').exists() and not (root / 'docs' / 'guide.md').exists()
    assert {p: (root / p).read_bytes() for p in before} == before
    assert undo_last(root, hist) == []

def test_bom_and_crlf_preserved(tmp_path):
    root = make(tmp_path)
    ops = parse_ops('```edit:README.md\n<<<<<<< SEARCH\nline two\n=======\nline 2\nline 3\n>>>>>>> REPLACE\n```')
    changes = plan_changes(root, ops); apply_changes(root, changes, tmp_path / 'h')
    assert (root / 'README.md').read_bytes() == b'\xef\xbb\xbf# Title\r\nline 2\r\nline 3\r\n'

def test_apply_refuses_when_file_changed_after_planning(tmp_path):
    root = make(tmp_path)
    changes = plan_changes(root, parse_ops('```file:src/app.py\nnew\n```'))
    (root / 'src' / 'app.py').write_text('edited by user\n')
    with pytest.raises(PathError): apply_changes(root, changes, tmp_path / 'h')
    assert (root / 'src' / 'app.py').read_text() == 'edited by user\n'

def test_selective_apply_only_touches_chosen(tmp_path):
    root = make(tmp_path)
    changes = plan_changes(root, parse_ops(REPLY)); changes[1].state = 'rejected'
    apply_changes(root, [changes[0]], tmp_path / 'h')
    assert (root / 'src' / 'new_module.py').exists() and 'return 2' in (root / 'src' / 'app.py').read_text() and (root / 'README.md').exists()

def test_prompt_contains_protocol_tree_files_and_mentions(tmp_path):
    root = make(tmp_path)
    prompt, report = core.build_prompt(root, 'لطفاً @app.py را درست کن', [])
    assert prompt.startswith(core.PROJECT_INSTRUCTION) and 'src/\n  app.py' in prompt and 'Current content of src/app.py' in prompt
    assert prompt.endswith('لطفاً @app.py را درست کن') and report == [('src/app.py', len((root / 'src' / 'app.py').read_text()), '')]
    big = root / 'big.txt'; big.write_text('x' * (core.MAX_FILE_BYTES + 10))
    _, report = core.build_prompt(root, 'hi', ['big.txt', '../out.txt']); assert report == [('big.txt', 0, 'too_large'), ('../out.txt', 0, 'unreadable')]
