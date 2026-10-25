import json
from pathlib import Path
import subprocess
import sys

import pytest

from self_dialogue_lab.store import Store
from self_dialogue_lab.responder import MockResponder
from self_dialogue_lab.service import converse


def test_records_conversation_and_feedback_survive_new_process(tmp_path):
    path = tmp_path / 'persistent.sqlite3'
    db = Store(path)
    id = db.add('自分で登録した考え', '理由', '文脈', '2026-10-24T10:00')
    converse(db, MockResponder(), 'テスト用発言', 'E. 保存候補を承認または拒否する')
    db.write('INSERT INTO feedback VALUES(?,?)', (1, json.dumps(['有益な問い'], ensure_ascii=False)))
    db.db.close()
    code = '''
import json, sys
from self_dialogue_lab.store import Store
db = Store(sys.argv[1])
assert db.records()[0]['thought'] == '自分で登録した考え'
assert db.records()[0]['reason'] == '理由'
assert db.records()[0]['occurred'] == '2026-10-24T10:00'
assert db.rows('SELECT body FROM messages')[0]['body'] == 'テスト用発言'
assert len(db.rows('SELECT * FROM responses')) == 1
assert db.rows('SELECT status FROM candidates')[0]['status'] == 'pending'
assert json.loads(db.rows('SELECT labels FROM feedback')[0]['labels']) == ['有益な問い']
db.db.close()
'''
    result = subprocess.run([sys.executable, '-c', code, str(path)], cwd=Path(__file__).resolve().parents[1] / 'src', capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_seed_does_not_repeat_after_reopen_or_deletion(tmp_path):
    path = tmp_path / 'demo.sqlite3'
    db = Store(path)
    db.seed()
    assert len(db.records()) == 7
    db.write('DELETE FROM records WHERE id=1')
    db.db.close()
    reopened = Store(path)
    reopened.seed()
    assert len(reopened.records()) == 6
    assert not reopened.rows('SELECT * FROM records WHERE id=1')
    reopened.db.close()


def test_new_responses_exclude_changed_and_deleted_records(tmp_path):
    db = Store(tmp_path / 'refs.sqlite3')
    db.seed()
    converse(db, MockResponder(), '相談', 'A')
    assert {r['id'] for r in json.loads(db.rows('SELECT refs FROM responses')[0]['refs'])} == {1, 2}
    current = db.add('今は安定を重視したい', '考えの変化', '現在', previous_id=1)
    db.write('DELETE FROM records WHERE id=2')
    converse(db, MockResponder(), '相談', 'A')
    refs = json.loads(db.rows('SELECT refs FROM responses ORDER BY id DESC')[0]['refs'])
    assert {r['id'] for r in refs} == {current}
    assert {r['id'] for r in db.current_records()}.isdisjoint({1, 2})
    # 過去の写しと、新たに参照する現在の記録は別。
    assert {r['id'] for r in json.loads(db.rows('SELECT refs FROM responses ORDER BY id')[0]['refs'])} == {1, 2}
    db.db.close()


def test_clear_conversations_preserves_approved_records(tmp_path):
    db = Store(tmp_path / 'clear.sqlite3')
    converse(db, MockResponder(), '残したい考え', 'E. 保存候補を承認または拒否する')
    db.approve(1, '残したい考え', '理由', '文脈')
    db.write('INSERT INTO feedback VALUES(1,?)', ('["有益な問い"]',))
    before = db.export()
    db.clear_conversations()
    for table in ('messages', 'responses', 'feedback', 'candidates'):
        assert not db.rows(f'SELECT * FROM {table}')
    assert db.export() == before
    converse(db, MockResponder(), '次の会話', 'D. 関連記録がないときに質問する')
    assert len(db.rows('SELECT * FROM messages')) == 1
    db.db.close()


def test_demo_and_personal_databases_are_separate(tmp_path):
    demo = Store(tmp_path / 'demo.sqlite3')
    demo.seed()
    personal = Store(tmp_path / 'personal.sqlite3')
    assert personal.records() == []
    personal.add('自分の記録', '', '')
    assert len(demo.records()) == 7
    assert personal.records()[0]['thought'] == '自分の記録'
    demo.db.close()
    personal.db.close()


def test_ui_reload_and_delete_history(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'ui.sqlite3'
    monkeypatch.setenv('SELF_DIALOGUE_DB', str(path))
    monkeypatch.setenv('SELF_DIALOGUE_PERSONAL_DB', str(tmp_path / 'personal.sqlite3'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src' / 'lab.py')).run()
    assert not app.exception
    assert any('モック・固定応答' in w.value for w in app.warning)
    next(b for b in app.button if b.label == 'シナリオ例文を送信').click().run()
    next(b for b in app.button if b.label == '評価を保存').click().run()
    reloaded = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src' / 'lab.py')).run()
    assert not reloaded.exception
    assert len(reloaded.chat_message) == 2
    reloaded.sidebar.checkbox[0].check().run()
    next(b for b in reloaded.button if b.label == '会話履歴だけを削除').click().run()
    assert not reloaded.exception
    assert len(reloaded.chat_message) == 0
    db = Store(path)
    assert len(db.records()) == 7
    assert db.rows('SELECT * FROM feedback') == []
    db.db.close()
    reloaded.sidebar.selectbox[0].set_value('自分の記録（初期データなし）').run()
    assert not reloaded.exception
    personal = Store(tmp_path / 'personal.sqlite3')
    assert personal.records() == []
    personal.db.close()
