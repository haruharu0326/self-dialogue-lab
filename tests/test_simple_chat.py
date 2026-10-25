from pathlib import Path
import pytest

from self_dialogue_lab.responder import Reply
from self_dialogue_lab.service import converse_personal
from self_dialogue_lab.store import Store


class CapturingResponder:
    model = 'test-adapter'

    def __init__(self):
        self.inputs = []

    def respond(self, message, scenario, records, **kwargs):
        self.inputs.append({'message': message, 'records': records, **kwargs})
        return Reply('考えを聞かせてください。', 'その理由は何ですか？', records)


def test_answers_only_become_memory_after_user_confirmation(tmp_path):
    path = tmp_path/'personal.sqlite3'
    db = Store(path)
    client = CapturingResponder()
    converse_personal(db, client, '私は家族との時間を大切にしたい', consent=True)
    assert client.inputs[-1]['records'] == []
    assert client.inputs[-1]['demo'] is False
    assert db.records() == []
    candidate = db.rows('SELECT * FROM candidates')[0]
    db.approve(candidate['id'], '家族との時間を大切にしたい', '', '本人が確認')
    db.db.close()

    db = Store(path)
    converse_personal(db, client, '転職について相談したい', consent=True)
    assert [r['thought'] for r in client.inputs[-1]['records']] == ['家族との時間を大切にしたい']
    assert client.inputs[-1]['history'][0]['text'] == '私は家族との時間を大切にしたい'
    assert len(db.records()) == 1
    with pytest.raises(ValueError):
        db.approve(candidate['id'], '二重保存', '', '')
    db.db.close()


def test_rejected_and_forgotten_answers_are_not_long_term_context(tmp_path):
    db = Store(tmp_path/'personal.sqlite3')
    client = CapturingResponder()
    converse_personal(db, client, 'まだ仮の考えです', consent=True)
    db.reject(1)
    converse_personal(db, client, '次の話', consent=True)
    assert client.inputs[-1]['records'] == []
    # 短期の会話文脈と、確認した長期記憶は別。
    assert client.inputs[-1]['history'][0]['text'] == 'まだ仮の考えです'
    db.approve(2, '後で覚える内容', '', '')
    id = db.records()[0]['id']
    db.delete_record(id)
    converse_personal(db, client, '今の考え', consent=True)
    assert client.inputs[-1]['records'] == []
    assert len(db.rows('SELECT * FROM responses')) == 3
    db.db.close()


def test_personal_chat_without_consent_does_not_call_model(tmp_path):
    db = Store(tmp_path/'personal.sqlite3')
    client = CapturingResponder()
    with pytest.raises(ValueError):
        converse_personal(db, client, '相談', consent=False)
    assert client.inputs == []
    assert db.rows('SELECT * FROM messages') == []
    db.db.close()


def test_product_screen_has_no_lab_controls_or_sample_records(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    path = tmp_path/'personal.sqlite3'
    monkeypatch.setenv('SELF_DIALOGUE_PERSONAL_DB', str(path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'src/app.py')).run()
    assert not app.exception
    assert not app.selectbox and not app.radio and not app.multiselect
    assert app.chat_input[0].disabled
    db = Store(path)
    assert db.records() == []
    assert db.rows('SELECT * FROM meta') == []
    db.db.close()
