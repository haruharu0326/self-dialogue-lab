"""PostToolUse: docs/ と README.md の編集後に文書の整合テストだけを流す。

文書一覧（tests/test_integrity.pyの期待値）と相対リンクの切れをその場で検出する。
失敗時は終了コード2で結果をClaudeへ返す。pytestが見つからない場合は警告だけ出す。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get('CLAUDE_PROJECT_DIR') or Path(__file__).resolve().parents[2])
TESTS = ['tests/test_integrity.py::test_document_paths_and_relative_links_exist',
         'tests/test_integrity.py::test_git_excludes_private_files_but_not_docs_or_samples']


def is_doc(raw):
    try:
        rel = Path(raw).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return False
    return rel == 'README.md' or (rel.startswith('docs/') and rel.endswith('.md'))


def pytest_python():
    """.venvにpytestが無い環境があるため、py -0pの一覧からpytest入りの処理系を探す。"""
    candidates = [sys.executable]
    if shutil.which('py'):
        listed = subprocess.run(['py', '-0p'], capture_output=True, text=True).stdout
        candidates += [line.split()[-1] for line in listed.splitlines() if line.strip().endswith('.exe')]
    for exe in dict.fromkeys(candidates):
        if subprocess.run([exe, '-c', 'import pytest'], capture_output=True).returncode == 0:
            return exe
    return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # Windowsの既定cp932では日本語が文字化けする
    sys.stderr.reconfigure(encoding='utf-8')
    data = json.load(sys.stdin)
    tool_input = data.get('tool_input') or {}
    path = tool_input.get('file_path') or (data.get('tool_response') or {}).get('filePath') or ''
    if not is_doc(path):
        return 0
    exe = pytest_python()
    if not exe:
        print(json.dumps({'systemMessage': '文書テストを実行できません: pytestが入ったPythonが見つかりません。'},
                         ensure_ascii=False))
        return 0
    with tempfile.TemporaryDirectory(prefix='claude-doc-hook-') as temp:
        result = subprocess.run([exe, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', f'--basetemp={temp}/t', *TESTS],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if result.returncode != 0:
        tail = '\n'.join((result.stdout + result.stderr).strip().splitlines()[-25:])
        print(f'文書の整合テストが失敗しました（{Path(path).name}の編集後）。リンク切れや文書一覧の期待値を確認してください。\n{tail}',
              file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
