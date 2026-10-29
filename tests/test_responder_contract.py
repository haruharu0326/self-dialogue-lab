"""NFR-013 / AT-032〜034,039: 通常経路の応答器契約。代替応答器の成功は実モデルの対話品質の評価ではない。"""
import inspect
import json

import pytest
from fastapi.testclient import TestClient

from self_dialogue_lab.api import create_app
from self_dialogue_lab.gemini import GeminiResponder
from self_dialogue_lab.responder import MockResponder, Reply, Responder, ResponderError
from self_dialogue_lab.service import IDENTITY_ERROR, REPLY_ERROR, converse_gemini, converse_personal
from self_dialogue_lab.store import Store

CONTRACT = [('self', inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
            ('message', inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
            ('scenario', inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
            ('records', inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
            ('correction_of', inspect.Parameter.KEYWORD_ONLY, None),
            ('change_from', inspect.Parameter.KEYWORD_ONLY, None),
            ('history', inspect.Parameter.KEYWORD_ONLY, None),
            ('demo', inspect.Parameter.KEYWORD_ONLY, False),
            ('tone_context', inspect.Parameter.KEYWORD_ONLY, None)]


class StrictResponder:
    """**kwargsを持たない、契約どおりの代替応答器。"""
    provider = 'strict-test'
    model = 'strict-test-v1'

    def __init__(self, refs=None, mutate=False, text='代替応答器の返答', question='その理由は何ですか？'):
        self.calls = []
        self.refs = refs
        self.mutate = mutate
        self.text, self.question = text, question

    def respond(self, message, scenario, records, *, correction_of=None, change_from=None, history=None, demo=False, tone_context=None):
        self.calls.append({'message': message, 'records': records, 'correction_of': correction_of, 'change_from': change_from,
                           'history': history, 'demo': demo, 'tone_context': tone_context})
        if self.mutate:
            for record in records:
                record['thought'] = '応答器が書き換えた本文'
        refs = records if self.refs is None else self.refs
        return Reply(self.text, self.question, refs)


def signature(method):
    return [(p.name, p.kind, p.default) for p in inspect.signature(method).parameters.values()]


def counts(db):
    return {table: db.rows(f'SELECT COUNT(*) AS n FROM {table}')[0]['n'] for table in ('messages', 'responses', 'candidates', 'records')}


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path / 'personal.sqlite3')
    yield store
    store.db.close()


def test_responders_match_the_contract_signature():
    for cls in (Responder, GeminiResponder, MockResponder, StrictResponder):
        assert signature(cls.respond) == CONTRACT, cls
    for responder in (GeminiResponder(api_key='test-only', transport=object()), MockResponder(), StrictResponder()):
        assert isinstance(responder.provider, str) and responder.provider
        assert isinstance(responder.model, str) and responder.model
    assert (GeminiResponder.provider, MockResponder.provider) == ('gemini', 'mock')


def test_strict_responder_runs_the_normal_path_and_saves_provider_and_model(db):
    responder = StrictResponder()
    converse_personal(db, responder, '家族との時間を大切にしたい', consent=True)
    call = responder.calls[-1]
    assert call['records'] == [] and call['history'] == [] and call['demo'] is False and call['tone_context'] is None
    body = json.loads(db.rows('SELECT body FROM responses')[0]['body'])
    assert (body['provider'], body['model']) == ('strict-test', 'strict-test-v1')
    candidate = db.rows('SELECT * FROM candidates')[0]
    assert candidate['status'] == 'pending' and candidate['context'] == 'チャットの本人発言（原文候補）'

    converse_personal(db, responder, '今の気分', consent=True, tone_context={'label': '中立', 'score': 0.5})
    assert responder.calls[-1]['tone_context'] == {'label': '中立', 'score': 0.5}


def test_mock_responder_accepts_the_normal_path_arguments(db):
    db.add('裁量を大切にしたい', '', '')
    converse_personal(db, MockResponder(), '相談', consent=True, tone_context={'label': '中立', 'score': 0.5})
    row = db.rows('SELECT * FROM responses')[0]
    body = json.loads(row['body'])
    assert (body['provider'], body['model']) == ('mock', 'mock-fixed')
    assert [r['thought'] for r in json.loads(row['refs'])] == ['裁量を大切にしたい']


@pytest.mark.parametrize('refs', [[{'id': 999, 'thought': '架空の記録'}], [{'thought': 'IDなし'}], ['1'], [{'id': '1'}], 'unsupplied'])
def test_unsupplied_references_are_rejected_before_saving(db, refs):
    first = db.add('一つ目', '', '')
    second = db.add('二つ目（今回は渡さない）', '', '')
    converse_personal(db, StrictResponder(), '最初の会話', consent=True)
    before = counts(db)
    if refs == 'unsupplied':
        refs = [{'id': second, 'thought': '二つ目'}]
    responder = StrictResponder(refs=refs)
    with pytest.raises(ResponderError) as error:
        converse_gemini(db, responder, '相談', reference_ids=[first], consent=True)
    assert str(error.value) == REPLY_ERROR
    assert counts(db) == before and len(responder.calls) == 1


def test_saved_references_are_db_copies_not_responder_output(db):
    keep = db.add('家族の時間', '理由', '文脈')
    converse_personal(db, StrictResponder(refs=[{'id': keep, 'thought': '捏造した本文'}, {'id': keep}]), '相談', consent=True)
    converse_personal(db, StrictResponder(mutate=True), '次の相談', consent=True)
    for row in db.rows('SELECT refs FROM responses'):
        refs = json.loads(row['refs'])
        assert [r['thought'] for r in refs] == ['家族の時間'] and refs[0]['reason'] == '理由'
    assert db.current_records()[0]['thought'] == '家族の時間'


def test_only_current_approved_records_are_supplied(db):
    """AT-033,035: 未承認・拒否・削除済み・過去扱いの記録はrecordsに入らない。"""
    for text in ('承認する発言', '拒否する発言', '保留する発言', '忘れる発言'):
        converse_personal(db, StrictResponder(), text, consent=True)
    ids = {c['thought']: c['id'] for c in db.rows('SELECT * FROM candidates')}
    db.approve(ids['承認する発言'], '承認した記憶', '', '')
    db.reject(ids['拒否する発言'])
    db.approve(ids['忘れる発言'], '忘れる記憶', '', '')
    forgotten = next(r['id'] for r in db.records() if r['thought'] == '忘れる記憶')
    db.delete_record(forgotten)
    old = db.add('以前の立場', '', '')
    new = db.add('今の立場', '', '', previous_id=old)

    responder = StrictResponder()
    converse_personal(db, responder, '相談', consent=True)
    supplied = responder.calls[-1]['records']
    assert sorted(r['thought'] for r in supplied) == ['今の立場', '承認した記憶']
    assert old not in [r['id'] for r in supplied] and new in [r['id'] for r in supplied]
    with pytest.raises(ResponderError):
        converse_gemini(db, StrictResponder(refs=[{'id': old}]), '相談', reference_ids=[new], consent=True)


def test_api_shows_saved_provider_and_rejects_fake_references(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    path = tmp_path / 'personal.sqlite3'
    factory = {'refs': None}
    app = create_app(str(path), responder_factory=lambda: StrictResponder(refs=factory['refs']), static_dir=tmp_path / 'missing')
    client = TestClient(app, base_url='http://127.0.0.1:8501')
    state = client.post('/api/messages', json={'text': '家族との時間', 'consent': True}).json()
    # 表示文言はFR-028で決めるため、画面状態ではgemini以外をmockへ正規化する。DBには実際のproviderを残す。
    assert state['exchanges'][0]['reply']['provider'] == 'mock'
    db = Store(path)
    assert json.loads(db.rows('SELECT body FROM responses')[0]['body'])['provider'] == 'strict-test'
    db.db.close()

    factory['refs'] = [{'id': 999, 'thought': '架空の記録'}]
    db = Store(path)
    before = counts(db)
    response = client.post('/api/messages', json={'text': '相談', 'consent': True})
    assert response.status_code == 502 and response.json() == {'detail': REPLY_ERROR}
    assert counts(db) == before
    db.db.close()


@pytest.mark.parametrize('attribute,value', [('provider', ''), ('provider', '  '), ('provider', None), ('model', ''),
                                             ('model', 1), ('provider', 'missing'), ('model', 'missing')])
def test_provider_and_model_must_be_non_empty_strings(db, attribute, value):
    responder = StrictResponder()
    if value == 'missing':
        class Anonymous:
            respond = staticmethod(responder.respond)
        target = Anonymous()
        setattr(target, 'model' if attribute == 'provider' else 'provider', 'x')
    else:
        target = responder
        setattr(target, attribute, value)
    before = counts(db)
    with pytest.raises(ResponderError) as error:
        converse_personal(db, target, '相談', consent=True)
    assert str(error.value) == IDENTITY_ERROR
    assert responder.calls == [] and counts(db) == before


@pytest.mark.parametrize('text', ['', '   ', '\n'])
def test_blank_interpretation_is_rejected_before_saving(db, text):
    before = counts(db)
    with pytest.raises(ResponderError):
        converse_personal(db, StrictResponder(text=text), '相談', consent=True)
    assert counts(db) == before


def test_empty_question_is_allowed_like_the_gemini_adapter(db):
    converse_personal(db, StrictResponder(question=''), '相談', consent=True)
    assert json.loads(db.rows('SELECT body FROM responses')[0]['body'])['question'] == ''


class Crashing(StrictResponder):
    def respond(self, message, scenario, records, *, correction_of=None, change_from=None, history=None, demo=False, tone_context=None):
        raise RuntimeError('内部の詳細を含む例外')


def test_unexpected_responder_exception_saves_nothing(db, tmp_path, monkeypatch):
    """契約違反の任意の例外は何も保存しない。現状、APIでは500になる（例外文は返さない）。"""
    before = counts(db)
    with pytest.raises(RuntimeError):
        converse_personal(db, Crashing(), '相談', consent=True)
    assert counts(db) == before

    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    path = tmp_path / 'api' / 'personal.sqlite3'
    app = create_app(str(path), responder_factory=Crashing, static_dir=tmp_path / 'missing')
    client = TestClient(app, base_url='http://127.0.0.1:8501', raise_server_exceptions=False)
    response = client.post('/api/messages', json={'text': '相談', 'consent': True})
    assert response.status_code == 500 and '内部の詳細' not in response.text
    api_db = Store(path)
    assert counts(api_db) == {'messages': 0, 'responses': 0, 'candidates': 0, 'records': 0}
    api_db.db.close()
