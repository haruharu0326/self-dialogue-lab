"""Review boundaries, Git state, result validation and orchestration without model calls."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


@pytest.fixture
def review():
    spec = spec_from_file_location('review_harness', Path(__file__).resolve().parents[1] / 'scripts/review.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path, review, monkeypatch):
    def git(*args):
        subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)

    git('init')
    (tmp_path / 'README.md').write_text('old\n', encoding='utf-8')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/deleted.py').write_text('old = True\n', encoding='utf-8')
    git('add', '.')
    git('-c', 'user.name=Harness Test', '-c', 'user.email=harness@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')
    monkeypatch.setattr(review, 'ROOT', tmp_path)
    return tmp_path, git


def clean_review():
    return {'summary': '対象差分に指摘なし。', 'findings': [], 'blockers': []}


def report(repo):
    return json.loads(next((repo / '.review-runs').glob('*/report.json')).read_text(encoding='utf-8'))


def test_snapshot_covers_index_worktree_untracked_and_deletions(review, repo):
    root, git = repo
    (root / 'README.md').write_text('staged\n', encoding='utf-8')
    git('add', 'README.md')
    (root / 'README.md').write_text('current\n', encoding='utf-8')
    (root / 'src/deleted.py').unlink()
    (root / 'src/new.py').write_text('new = True\n', encoding='utf-8')
    payload = review.snapshot(root, 'HEAD')
    changes = {item['path']: item for item in payload['changes']}
    assert set(changes) == {'README.md', 'src/new.py', 'src/deleted.py'}
    assert changes['README.md']['before'] == 'old\n'
    assert changes['README.md']['after'] == 'current\n'
    assert changes['src/deleted.py']['after'] is None
    assert changes['src/new.py']['before'] is None
    selected = review.snapshot(root, 'HEAD', ['src/new.py'])
    assert [item['path'] for item in selected['changes']] == ['src/new.py']
    with pytest.raises(review.ReviewError):
        review.snapshot(root, 'HEAD', ['../secret.py'])


@pytest.mark.parametrize('path', ['.env', 'src/.env.py', 'src/private/key.py', 'src/data/person.md',
                                      'src/secret.py', 'src/samples/thoughts.json', 'frontend/node_modules/a.ts',
                                      'src/self_dialogue_lab/static/a.html', '../src/a.py', 'C:/src/a.py'])
def test_private_and_generated_paths_are_excluded(review, path):
    assert not review.allowed(path)


def test_sensitive_files_do_not_enter_payload_and_oversize_is_failure(review, repo, monkeypatch):
    root, _ = repo
    (root / '.env').write_text('SENSITIVE_VALUE', encoding='utf-8')
    (root / 'src/private').mkdir()
    (root / 'src/private/info.md').write_text('SENSITIVE_VALUE', encoding='utf-8')
    payload = review.snapshot(root, 'HEAD')
    assert 'SENSITIVE_VALUE' not in json.dumps(payload)
    assert payload['excluded_changes'] == 2
    monkeypatch.setattr(review, 'MAX_INPUT', 10)
    with pytest.raises(review.ReviewError):
        review.snapshot(root, 'HEAD')


def test_link_cannot_escape_repository(review, repo, monkeypatch):
    root, _ = repo
    original_resolve = review.Path.resolve
    monkeypatch.setattr(review.Path, 'resolve', lambda self: root.parent / 'outside.py' if self.name == 'README.md' else original_resolve(self))
    with pytest.raises(review.ReviewError):
        review.read_current(root, 'README.md')


@pytest.mark.parametrize('mutation', ['outside', 'line', 'boolean_line', 'missing', 'empty', 'severity'])
def test_rejects_invalid_or_unscoped_findings(review, repo, mutation):
    root, _ = repo
    (root / 'README.md').write_text('new\n', encoding='utf-8')
    payload = review.snapshot(root, 'HEAD')
    finding = dict(severity='P1', path='README.md', line=1, title='issue', condition='when',
                   impact='effect', basis='AGENTS.md', validation='reproduce')
    if mutation == 'outside':
        finding['path'] = 'src/unchanged.py'
    elif mutation == 'line':
        finding['line'] = 200
    elif mutation == 'boolean_line':
        finding['line'] = True
    elif mutation == 'missing':
        del finding['basis']
    elif mutation == 'empty':
        finding['condition'] = ' '
    else:
        finding['severity'] = 'unknown'
    with pytest.raises(review.ReviewError):
        review.validate_review({**clean_review(), 'findings': [finding]}, payload)


def test_prepare_only_never_calls_model_or_verification(review, repo, monkeypatch):
    root, _ = repo
    (root / 'README.md').write_text('new\n', encoding='utf-8')
    monkeypatch.setattr(review, 'run_codex', lambda *args: pytest.fail('must not call model'))
    assert review.main(['--prepare-only']) == 2
    result = report(root)
    assert result['status'] == 'not-run' and result['review'] is None
    assert result['verification']['exit_code'] is None


@pytest.mark.parametrize('mode,expected', [('clean', 2), ('stale', 2), ('invalid', 1), ('failure', 1)])
def test_model_results_and_stale_snapshot_are_never_false_success(review, repo, monkeypatch, mode, expected):
    root, _ = repo
    (root / 'README.md').write_text('new\n', encoding='utf-8')

    def model(text, output, timeout, model):
        assert 'verification' in text and 'AGENTS.md' in text
        if mode == 'failure':
            raise review.ReviewError('synthetic CLI failure')
        if mode == 'stale':
            (root / 'README.md').write_text('changed during review\n', encoding='utf-8')
        value = {'summary': ''} if mode == 'invalid' else clean_review()
        review.save_json(output, value)
        return value

    monkeypatch.setattr(review, 'run_codex', model)
    assert review.main(['--skip-verify']) == expected
    result = report(root)
    assert result['exit_code'] == expected
    if mode == 'stale':
        assert result['stale'] is True
    if mode in ('invalid', 'failure'):
        assert result['review'] is None and result['status'] == 'failed'


@pytest.mark.parametrize('verify_code,blockers,expected', [(0, [], 0), (2, [], 2), (1, [], 1), (0, ['仕様衝突'], 2)])
def test_verification_and_blockers_control_exit_code(review, repo, monkeypatch, verify_code, blockers, expected):
    root, _ = repo
    (root / 'README.md').write_text('new\n', encoding='utf-8')
    original_run = review.subprocess.run

    def execute(command, **kwargs):
        if 'verify.py' not in ' '.join(command):
            return original_run(command, **kwargs)
        path = Path(command[-1])
        review.save_json(path, {'exit_code': verify_code, 'stages': [{'name': 'synthetic', 'status': 'passed'}]})
        return subprocess.CompletedProcess(command, verify_code)

    monkeypatch.setattr(review.subprocess, 'run', execute)
    monkeypatch.setattr(review, 'run_codex', lambda *args: {**clean_review(), 'blockers': blockers})
    assert review.main([]) == expected
    assert report(root)['exit_code'] == expected


def test_cli_boundary_uses_stdin_schema_and_read_only(review, tmp_path, monkeypatch):
    """Exercise a real child process with a synthetic CLI, without network or model calls."""
    helper = tmp_path / 'synthetic_cli.py'
    helper.write_text('import json,sys\np=json.load(sys.stdin)\n'
                      'assert p["sentinel"] == "quoted $() text"\n'
                      'json.dump({"summary":"synthetic", "findings":[], "blockers":[]},open(sys.argv[1],"w"))\n', encoding='utf-8')
    output = tmp_path / 'review.json'
    real_popen = review.subprocess.Popen
    real_run = review.subprocess.run
    monkeypatch.setattr(review.shutil, 'which', lambda name: 'synthetic-codex')

    def execute(command, **kwargs):
        if command[:3] == ['synthetic-codex', 'login', 'status']:
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, **kwargs)

    def start(command, **kwargs):
        assert command[:5] == ['synthetic-codex', '-a', 'never', 'exec', '--sandbox']
        assert command[5] == 'read-only'
        assert '--ephemeral' in command and '--output-schema' in command
        assert command[-1] == '-' and kwargs.get('shell', False) is False
        assert Path(kwargs['cwd']) != review.ROOT
        return real_popen([sys.executable, str(helper), str(output)], **kwargs)

    monkeypatch.setattr(review.subprocess, 'run', execute)
    monkeypatch.setattr(review.subprocess, 'Popen', start)
    result = review.run_codex(json.dumps({'sentinel': 'quoted $() text'}), output, 10)
    assert result['summary'] == 'synthetic'


def test_unauthenticated_cli_never_starts_model(review, tmp_path, monkeypatch):
    monkeypatch.setattr(review.shutil, 'which', lambda name: 'synthetic-codex')
    monkeypatch.setattr(review.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1))
    monkeypatch.setattr(review.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('no model call expected'))
    with pytest.raises(review.ReviewError, match='not logged in'):
        review.run_codex('input', tmp_path / 'result.json', 10)


def test_timeout_covers_large_input_when_child_never_reads_stdin(review, tmp_path, monkeypatch):
    helper = tmp_path / 'unresponsive_cli.py'
    helper.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
    real_popen = review.subprocess.Popen
    children = []
    monkeypatch.setattr(review.shutil, 'which', lambda name: 'synthetic-codex')

    def start(command, **kwargs):
        assert kwargs['stdin'] != subprocess.PIPE
        process = real_popen([sys.executable, str(helper)], **kwargs)
        children.append(process)
        return process

    def execute(command, **kwargs):
        if command[0] == 'taskkill':
            assert str(children[0].pid) in command
            children[0].kill()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(review.subprocess, 'Popen', start)
    monkeypatch.setattr(review.subprocess, 'run', execute)
    begin = time.monotonic()
    with pytest.raises(review.ReviewError, match='timed out'):
        review.run_codex('x' * 500_000, tmp_path / 'result.json', 1)
    assert time.monotonic() - begin < 10
    assert children[0].poll() is not None
