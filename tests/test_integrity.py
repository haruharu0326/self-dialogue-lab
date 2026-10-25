import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import tomllib

import pytest

from self_dialogue_lab.responder import MockResponder, Reply
from self_dialogue_lab.service import converse
from self_dialogue_lab.store import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path / 'integrity.sqlite3')
    yield store
    store.db.close()


def test_record_crud_order_validation_and_export(db):
    """AT-001,002,003,015: CRUDと入力不備、JSONの境界。"""
    first = db.add('  考え①  ', '理由①', '文脈①', '2026-10-20T10:00')
    second = db.add('考え②', '', '', '2026-10-21T10:00')
    assert [r['id'] for r in db.records()] == [second, first]
    db.edit(first, '  修正後  ', '理由変更', '文脈変更', '2026-10-22T10:00')
    records = db.records()
    assert len(records) == 2 and records[0]['id'] == first
    assert records[0]['thought'] == '修正後'
    assert records[0]['reason'] == '理由変更'
    assert json.loads(db.export()) == records
    for operation in (
        lambda: db.add(' ', '', ''),
        lambda: db.edit(first, ' ', '', '', '2026-10-22T10:00'),
        lambda: db.edit(999, '考え', '', '', '2026-10-22T10:00'),
        lambda: db.delete_record(999),
        lambda: db.add('変化', '', '', previous_id=999),
    ):
        with pytest.raises(ValueError):
            operation()
        assert db.records() == records
    db.delete_record(first)
    db.delete_record(second)
    assert json.loads(db.export()) == []


def test_historical_record_does_not_reactivate_after_descendant_deleted(db):
    """AT-004: 新しい記録の削除で過去の立場を自動復活させない。"""
    old = db.add('裁量を優先', '', '')
    new = db.add('安定を優先', '', '', previous_id=old)
    db.delete_record(new)
    assert db.current_records() == []
    db.edit(old, '裁量を重視（誤字修正）', '', '', '2026-10-24T10:00')
    assert db.current_records() == []
    reply = MockResponder().respond('相談', 'A', db.records())
    assert reply.references == []


def test_deleted_source_id_not_reused_and_candidate_cannot_be_mislinked(db):
    """AT-012: 削除した変更元IDの再利用による誤承認を防ぐ。"""
    old = db.add('以前の考え', '', '')
    converse(db, MockResponder(), '新しい考え', 'C. 以前とは考えが変わった', previous_id=old)
    db.delete_record(old)
    unrelated = db.add('無関係の記録', '', '')
    assert unrelated > old
    with pytest.raises(ValueError, match='削除'):
        db.approve(1, '新しい考え', '', '')
    assert len(db.records()) == 1
    db.reject(1)
    assert db.rows('SELECT status FROM candidates')[0]['status'] == 'rejected'


def test_approval_failure_rolls_back_record_and_historical_flag(db):
    """AT-011: INSERT成功後にUPDATEが失敗しても、途中の追加を残さない。"""
    old = db.add('元の立場', '', '')
    converse(db, MockResponder(), '新しい立場', 'C. 以前とは考えが変わった', previous_id=old)
    before = db.export()
    db.write("""CREATE TRIGGER fail_approval BEFORE UPDATE ON candidates
        BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        db.approve(1, '新しい立場', '理由', '文脈')
    assert db.export() == before
    assert db.rows('SELECT status FROM candidates')[0]['status'] == 'pending'
    db.write('DROP TRIGGER fail_approval')
    db.approve(1, '新しい立場', '', '')
    assert len(db.records()) == 2


def test_conversation_and_seed_failures_are_atomic(db):
    """AT-011,016: 会話と初期投入の途中失敗をロールバック。"""
    db.write("""CREATE TRIGGER fail_response BEFORE INSERT ON responses
        BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        converse(db, MockResponder(), '入力', 'E. 保存候補を承認または拒否する')
    for table in ('messages', 'responses', 'candidates'):
        assert db.rows(f'SELECT * FROM {table}') == []
    db.write('DROP TRIGGER fail_response')
    db.write("""CREATE TRIGGER fail_seed BEFORE INSERT ON records
        WHEN NEW.thought='収入の安定も守りたい'
        BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        db.seed()
    assert db.records() == []
    assert db.rows('SELECT * FROM meta') == []


def test_feedback_replaces_and_validates_labels(db):
    """AT-013: 同じ応答は1行、定義外と消失応答は拒否。"""
    converse(db, MockResponder(), '発言', 'E. 保存候補を承認または拒否する')
    db.save_feedback(1, ['有益な問い'])
    db.save_feedback(1, ['決めつけがある'])
    assert len(db.rows('SELECT * FROM feedback')) == 1
    assert json.loads(db.rows('SELECT labels FROM feedback')[0]['labels']) == ['決めつけがある']
    with pytest.raises(ValueError):
        db.save_feedback(1, ['未定義'])
    with pytest.raises(ValueError):
        db.save_feedback(999, [])


def test_legacy_schema_migration_preserves_links_and_history(tmp_path):
    """AT-004,012: 既存DB移行で記録・参照関係を保持する。"""
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as old:
        old.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE records(id INTEGER PRIMARY KEY, thought TEXT NOT NULL, reason TEXT,
                context TEXT, occurred TEXT, previous_id INTEGER REFERENCES records(id) ON DELETE SET NULL);
            INSERT INTO records VALUES(1,'昔の考え','','','2026-10-01T10:00',NULL);
            INSERT INTO records VALUES(2,'今の考え','','','2026-10-24T10:00',1);
        ''')
    db = Store(path)
    assert [r['id'] for r in db.current_records()] == [2]
    assert db.rows('PRAGMA foreign_key_check') == []
    db.delete_record(2)
    db.db.close()
    db = Store(path)
    assert db.current_records() == []
    assert db.add('別の考え', '', '') > 2
    db.db.close()


def test_app_uses_no_network_and_responder_can_be_replaced(db, monkeypatch, capsys):
    """AT-023,024: 業務処理の通信禁止と応答器注入。LLM品質の評価ではない。"""
    def forbidden(*args, **kwargs):
        raise AssertionError('Network is forbidden in this test')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    db.seed()
    old = db.records()[0]['id']
    db.add('新しい記録', '', '', previous_id=old)
    class Substitute:
        def respond(self, message, scenario, records, **kwargs):
            assert old not in [r['id'] for r in records]
            assert all(not r['superseded'] for r in records)
            return Reply('差し替えた固定応答', '確認しますか？', [])
    converse(db, Substitute(), '秘密を含むテスト用発言', 'A')
    for scenario in ('A', 'B. AIの解釈を訂正する', 'D. 関連記録がないときに質問する', 'E. 保存候補を承認または拒否する'):
        converse(db, MockResponder(), '試用発言', scenario)
    output = capsys.readouterr()
    assert output.out == '' and output.err == ''
    config = tomllib.loads((ROOT / '.streamlit/config.toml').read_text(encoding='utf-8'))
    assert config['browser']['gatherUsageStats'] is False
    assert config['server']['address'] == '127.0.0.1'


def test_git_excludes_private_files_but_not_docs_or_samples():
    """AT-022: 個人データと秘密を追跡対象にしない。"""
    ignored = ['data/demo.sqlite3', 'data/demo.sqlite3-wal', 'exports/personal.json', '.env',
               '.streamlit/secrets.toml', '.venv/file', '.test-temp-run/input.json', 'private-key.pem']
    result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], input=('\0'.join(ignored)+'\0').encode(),
                            cwd=ROOT, capture_output=True)
    assert set(result.stdout.decode().strip('\0').split('\0')) == set(ignored)
    included = ['src/self_dialogue_lab/samples/thoughts.json'] + [p.relative_to(ROOT).as_posix() for p in (ROOT/'docs').rglob('*.md')]
    result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], input=('\0'.join(included)+'\0').encode(),
                            cwd=ROOT, capture_output=True)
    assert result.stdout == b''


def test_document_paths_and_relative_links_exist():
    """配置変更による相対リンク切れや旧仕様の重複を防ぐ。"""
    expected = {
        'README.md', 'requirements/requirements-definition.md', 'requirements/functional-requirements.md',
        'requirements/non-functional-requirements.md', 'design/external-design.md', 'design/internal-design.md',
        'testing/acceptance-tests.md', 'development/harness-plan.md',
    }
    assert {p.relative_to(ROOT/'docs').as_posix() for p in (ROOT/'docs').rglob('*.md')} == expected
    for file in [ROOT/'README.md', *(ROOT/'docs').rglob('*.md')]:
        for destination in re.findall(r'\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
            if '://' not in destination:
                assert (file.parent / destination.split('#')[0]).exists(), (file, destination)


def test_ui_redacts_storage_error(tmp_path, monkeypatch):
    """AT-021: DB障害時の画面に例外本文や秘密を出さない。"""
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    import self_dialogue_lab.lab_ui as ui
    def fail(path):
        raise sqlite3.OperationalError('SECRET: private input and path')
    monkeypatch.setattr(ui, 'Store', fail)
    app = AppTest.from_file(str(ROOT/'src/lab.py')).run()
    assert not app.exception
    assert any('データの読み書きに失敗しました' in e.value for e in app.error)
    assert all('SECRET' not in e.value for e in app.error)


def test_ui_same_database_path_is_rejected(tmp_path, monkeypatch):
    """AT-017: 誤った設定で領域を混ぜない。"""
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    path = str(tmp_path/'same.sqlite3')
    monkeypatch.setenv('SELF_DIALOGUE_DB', path)
    monkeypatch.setenv('SELF_DIALOGUE_PERSONAL_DB', path)
    app = AppTest.from_file(str(ROOT/'src/lab.py')).run()
    assert not app.exception
    assert any('同じDBは指定できません' in e.value for e in app.error)
    assert not Path(path).exists()
