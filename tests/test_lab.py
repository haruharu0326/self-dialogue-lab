from pathlib import Path
import json
import pytest
from self_dialogue_lab.store import Store
from self_dialogue_lab.responder import MockResponder
from self_dialogue_lab.service import converse


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / 'test.sqlite3')
    s.seed()
    yield s
    s.db.close()


def test_seed_once_and_export(store):
    store.seed()
    assert len(json.loads(store.export())) == 7


def test_unapproved_and_rejected_candidates_never_enter_references(store):
    converse(store, MockResponder(), '未承認の裁量についての発言', 'A')
    candidate = store.rows('SELECT * FROM candidates')[0]
    assert len(store.records()) == 7
    reply = MockResponder().respond('相談', 'A', store.records())
    assert all(r['thought'] != candidate['thought'] for r in reply.references)
    store.write("UPDATE candidates SET status='rejected' WHERE id=?", (candidate['id'],))
    with pytest.raises(ValueError):
        store.approve(candidate['id'], '拒否済み', '', '')
    assert len(store.records()) == 7


def test_approval_is_edited_and_once_only(store):
    converse(store, MockResponder(), '原文', 'A')
    store.approve(1, '編集後', '理由', '文脈')
    assert len(store.records()) == 8
    assert any(r['thought'] == '編集後' for r in store.records())
    with pytest.raises(ValueError):
        store.approve(1, '二重承認', '', '')
    assert len(store.records()) == 8


def test_correction_vs_change_and_delete(store):
    original = store.rows('SELECT * FROM records WHERE id=1')[0]
    store.edit(1, '裁量について誤字を訂正', '理由', '文脈', original['occurred'])
    assert len(store.records()) == 7
    new_id = store.add('今は安定を優先', '変化の理由', '今の状況', previous_id=1)
    assert store.rows('SELECT previous_id FROM records WHERE id=?', (new_id,))[0]['previous_id'] == 1
    refs = MockResponder().respond('相談', 'A', store.records()).references
    assert 1 not in [r['id'] for r in refs]
    store.write('DELETE FROM records WHERE id=1')
    assert store.rows('SELECT previous_id FROM records WHERE id=?', (new_id,))[0]['previous_id'] is None


def test_empty_input(store):
    with pytest.raises(ValueError):
        converse(store, MockResponder(), ' ', 'A')
    assert not store.rows('SELECT * FROM messages')


def test_correction_retracts_interpretation_without_changing_records(store):
    before = store.export()
    converse(store, MockResponder(), '転職を迷っています', 'B. AIの解釈を訂正する')
    original = store.rows('SELECT * FROM responses')[0]
    assert '収入への不安' in json.loads(original['body'])['interpretation']
    correction = '収入ではなく、家族との時間が減ることが心配です'
    converse(store, MockResponder(), correction, 'B. AIの解釈を訂正する', correction_of=original['id'])
    responses = store.rows('SELECT * FROM responses ORDER BY id')
    revised = json.loads(responses[-1]['body'])
    assert revised['correction_of'] == original['id']
    assert '取り下げます' in revised['interpretation']
    assert correction in revised['interpretation']
    assert responses[0] == original
    assert store.export() == before
    candidate = store.rows('SELECT * FROM candidates ORDER BY id')[-1]
    assert candidate['status'] == 'pending'
    assert candidate['thought'] == correction
    assert '訂正' in candidate['context']
    store.approve(candidate['id'], correction, '', candidate['context'])
    assert any(r['thought'] == correction for r in store.records())


def test_invalid_correction_has_no_side_effect(store):
    with pytest.raises(ValueError):
        converse(store, MockResponder(), '訂正', 'B', correction_of=999)
    assert not store.rows('SELECT * FROM messages')


def test_scenario_c_approval_links_change_and_preserves_old_record(store):
    original = store.rows('SELECT * FROM records WHERE id=1')[0]
    converse(store, MockResponder(), '今は裁量より安定を優先したい', 'C. 以前とは考えが変わった',
             previous_id=1, reason='生活環境が変わった', context='働き方の見直し')
    candidate = store.rows('SELECT * FROM candidates')[0]
    assert candidate['previous_id'] == 1
    assert candidate['reason'] == '生活環境が変わった'
    assert len(store.records()) == 7
    assert json.loads(store.rows('SELECT refs FROM responses')[0]['refs'])[0] == original
    store.approve(candidate['id'], candidate['thought'], candidate['reason'], candidate['context'])
    assert len(store.records()) == 8
    assert store.rows('SELECT * FROM records WHERE id=1')[0] == {**original, 'superseded': 1}
    new = store.rows('SELECT * FROM records WHERE previous_id=1')[0]
    assert new['thought'] == candidate['thought']
    assert new['reason'] == candidate['reason']
    assert new['context'] == candidate['context']
    refs = MockResponder().respond('相談', 'A', store.records()).references
    assert 1 not in [r['id'] for r in refs]
    assert new['id'] in [r['id'] for r in refs]


def test_scenario_c_requires_existing_source(store):
    for previous_id in (None, 999):
        with pytest.raises(ValueError):
            converse(store, MockResponder(), '新しい考え', 'C. 以前とは考えが変わった', previous_id=previous_id)
    assert not store.rows('SELECT * FROM candidates')
    converse(store, MockResponder(), '新しい考え', 'C. 以前とは考えが変わった', previous_id=1)
    store.write('DELETE FROM records WHERE id=1')
    with pytest.raises(ValueError, match='削除'):
        store.approve(1, '新しい考え', '', '')
    assert store.rows('SELECT status FROM candidates')[0]['status'] == 'pending'
    assert len(store.records()) == 6


def test_scenario_c_rejection_does_not_change_long_term_records(store):
    before = store.export()
    converse(store, MockResponder(), '今の考え', 'C. 以前とは考えが変わった', previous_id=1)
    store.write("UPDATE candidates SET status='rejected' WHERE id=1")
    with pytest.raises(ValueError):
        store.approve(1, '今の考え', '', '')
    assert store.export() == before


def test_candidate_schema_migration(tmp_path):
    import sqlite3
    path = tmp_path / 'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE candidates(id INTEGER PRIMARY KEY, message_id INTEGER, thought TEXT, reason TEXT, context TEXT, status TEXT DEFAULT 'pending')")
        db.execute("INSERT INTO candidates(thought) VALUES('以前の候補')")
    migrated = Store(path)
    assert migrated.rows('SELECT * FROM candidates')[0]['previous_id'] is None
    assert migrated.rows('SELECT * FROM candidates')[0]['thought'] == '以前の候補'
    migrated.db.close()


@pytest.mark.parametrize('records', [[], [{'id': 1, 'thought': '裁量を大切にしたい', 'previous_id': None}]])
def test_scenario_d_no_evidence_does_not_infer_values(records):
    reply = MockResponder().respond('図書館のボランティアについて考えたい', 'D. 関連記録がないときに質問する', records)
    assert reply.references == []
    assert '関連する記録は見つかりません' in reply.interpretation
    assert '分かりません' in reply.interpretation
    assert 'どのように考えていますか？' in reply.question
    assert '裁量' not in reply.interpretation + reply.question
    assert '安定' not in reply.interpretation + reply.question


def test_scenario_d_persists_question_and_only_user_candidate(store):
    before = store.export()
    message = '図書館のボランティアについて考えたい'
    converse(store, MockResponder(), message, 'D. 関連記録がないときに質問する')
    response = store.rows('SELECT * FROM responses')[0]
    assert json.loads(response['refs']) == []
    assert 'どのように考えていますか？' in json.loads(response['body'])['question']
    candidate = store.rows('SELECT * FROM candidates')[0]
    assert candidate['thought'] == message
    assert candidate['status'] == 'pending'
    assert store.export() == before


def test_empty_record_fallback_asks_without_inference():
    reply = MockResponder().respond('相談', 'A', [])
    assert reply == MockResponder.without_evidence()


def test_scenario_e_edited_approval_and_rejection_boundary(store):
    scenario = 'E. 保存候補を承認または拒否する'
    converse(store, MockResponder(), '裁量についての承認用の原文', scenario)
    converse(store, MockResponder(), '安定についての拒否用の原文', scenario)
    before = store.export()
    responses = store.rows('SELECT * FROM responses')
    assert all(json.loads(r['refs']) == [] for r in responses)
    assert 'まだ長期記録には保存していません' in json.loads(responses[0]['body'])['interpretation']
    assert len(store.records()) == 7
    store.reject(2)
    assert store.export() == before
    store.approve(1, '裁量を優先して働きたい', '自分で判断したいから', '転職の検討')
    records = store.records()
    assert len(records) == 8
    saved = next(r for r in records if r['thought'] == '裁量を優先して働きたい')
    assert saved['reason'] == '自分で判断したいから'
    assert saved['context'] == '転職の検討'
    refs = MockResponder().respond('相談', 'A', records).references
    assert saved['id'] in [r['id'] for r in refs]
    assert all(r['thought'] != '安定についての拒否用の原文' for r in refs)
    assert store.rows('SELECT body FROM messages WHERE id=1')[0]['body'] == '裁量についての承認用の原文'
    for id in (1, 2):
        with pytest.raises(ValueError):
            store.reject(id)
        with pytest.raises(ValueError):
            store.approve(id, '二重処理', '', '')
    assert len(store.records()) == 8


def test_reject_missing_and_blank_approval_leave_state_unchanged(store):
    with pytest.raises(ValueError):
        store.reject(999)
    converse(store, MockResponder(), '本人の発言', 'E. 保存候補を承認または拒否する')
    with pytest.raises(ValueError):
        store.approve(1, ' ', '', '')
    assert store.rows('SELECT status FROM candidates')[0]['status'] == 'pending'
    assert len(store.records()) == 7


def test_ui_scenario_e(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    path = tmp_path / 'ui-e.sqlite3'
    monkeypatch.setenv('SELF_DIALOGUE_DB', str(path))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src' / 'lab.py')).run()
    next(s for s in app.selectbox if s.label == 'モックシナリオ').set_value('E. 保存候補を承認または拒否する').run()
    app.chat_input[0].set_value('裁量を優先したい').run()
    app.chat_input[0].set_value('安定についてはまだ保留').run()
    app.sidebar.radio[0].set_value('保存確認').run()
    app.text_area(key='candidate1t').set_value('仕事では裁量を優先したい')
    next(b for b in app.button if b.label == '編集内容を承認して保存').click().run()
    assert not app.exception
    assert any('承認' in s.value for s in app.success)
    next(b for b in app.button if b.label == '拒否する').click().run()
    assert not app.exception
    assert any('拒否' in s.value for s in app.success)
    db = Store(path)
    assert [r['status'] for r in db.rows('SELECT status FROM candidates ORDER BY id')] == ['approved', 'rejected']
    assert len(db.records()) == 8
    assert any(r['thought'] == '仕事では裁量を優先したい' for r in db.records())
    db.db.close()


def test_ui_scenario_d(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('SELF_DIALOGUE_DB', str(tmp_path / 'ui-d.sqlite3'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src' / 'lab.py')).run()
    next(s for s in app.selectbox if s.label == 'モックシナリオ').set_value('D. 関連記録がないときに質問する').run()
    app.chat_input[0].set_value('図書館のボランティアについて考えたい').run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert any('関連記録なし' in item.value for item in app.markdown)


def test_ui_smoke(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('SELF_DIALOGUE_DB', str(tmp_path / 'ui.sqlite3'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src' / 'lab.py')).run()
    assert not app.exception
    app.chat_input[0].set_value('転職の収入が不安です').run()
    assert not app.exception
    assert len(app.chat_message) == 2
    app.text_area[0].set_value('家族との時間が心配です')
    next(button for button in app.button if button.label == '訂正を送信').click().run()
    assert not app.exception
    assert len(app.chat_message) == 4
    app.sidebar.radio[0].set_value('保存確認').run()
    assert not app.exception
    next(b for b in app.button if b.label == '編集内容を承認して保存').click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value('考えの一覧').run()
    assert not app.exception
