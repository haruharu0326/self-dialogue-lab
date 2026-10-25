from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from self_dialogue_lab.gemini import GeminiError, GeminiResponder
from self_dialogue_lab.responder import MockResponder
from self_dialogue_lab.service import converse, converse_gemini
from self_dialogue_lab.store import Store


class Response(BytesIO):
    pass


def test_tone_context_is_bounded_and_not_reused(db):
    captured = []
    def transport(req, timeout):
        captured.append(json.loads(json.loads(req.data)['contents'][0]['parts'][0]['text']))
        return Response(envelope())
    client = GeminiResponder('test-key-only', transport=transport)
    converse_gemini(db, client, '相談', consent=True, tone_context={'label': '中立', 'score': 0.5, 'extra': 'omit'})
    assert captured[-1]['tone_context'] == {'label': '中立', 'score': 0.5,
                                           'source': 'local_text_classifier', 'max_input_tokens': 512}
    converse_gemini(db, client, '続き', consent=True)
    assert 'tone_context' not in json.dumps(captured[-1])
    for tone in ({'label': 'invalid', 'score': 0.5}, {'label': '中立', 'score': float('nan')},
                 {'label': '中立', 'score': True}, {'label': '中立', 'score': 2}):
        with pytest.raises(GeminiError):
            converse_gemini(db, client, '相談', consent=True, tone_context=tone)
    assert len(captured) == 2


def envelope(ids=(), text='話を聞かせてください', question='いま何を大切にしたいですか？', finish='STOP'):
    content = json.dumps({'interpretation': text, 'question': question, 'reference_ids': list(ids)}, ensure_ascii=False)
    return json.dumps({'candidates': [{'finishReason': finish, 'content': {'parts': [{'text': content}]}}]}, ensure_ascii=False).encode()


@pytest.fixture
def db(tmp_path):
    store = Store(tmp_path/'gemini.sqlite3')
    yield store
    store.db.close()


def test_gemini_conversation_context_and_source_separation(db):
    requests = []
    def transport(req, timeout):
        assert timeout == 120
        assert req.full_url.startswith('https://generativelanguage.googleapis.com/')
        assert '?' not in req.full_url and 'test-key-only' not in req.full_url
        assert req.get_header('X-goog-api-key') == 'test-key-only'
        requests.append(json.loads(json.loads(req.data)['contents'][0]['parts'][0]['text']))
        return Response(envelope())
    client = GeminiResponder('test-key-only', transport=transport)
    converse(db, MockResponder(), 'モックの発言', 'A')
    converse_gemini(db, client, '最初の相談', consent=True, demo=True)
    assert requests[0]['records'] == [] and requests[0]['history'] == []
    assert requests[0]['demo'] is True
    converse_gemini(db, client, 'もう少し考えたい', consent=True)
    assert requests[1]['history'][0] == {'role': 'user', 'text': '最初の相談'}
    assert 'モックの発言' not in json.dumps(requests[1], ensure_ascii=False)
    rows = db.rows('SELECT * FROM responses ORDER BY id')
    assert json.loads(rows[-1]['body'])['provider'] == 'gemini'
    assert len(db.records()) == 0
    assert len(db.rows("SELECT * FROM candidates WHERE status='pending'")) == 3
    assert 'test-key-only' not in str(db.rows('SELECT * FROM responses'))


def test_only_selected_current_records_are_sent_and_refs_are_db_snapshots(db):
    old = db.add('以前の立場', '', '')
    current = db.add('今の立場', '理由', '文脈', previous_id=old)
    other = db.add('選択しない記録', '', '')
    converse(db, MockResponder(), '未承認の候補', 'A')
    captured = []
    def transport(req, timeout):
        data = json.loads(json.loads(req.data)['contents'][0]['parts'][0]['text'])
        captured.append(data)
        return Response(envelope([current]))
    client = GeminiResponder('test-key-only', transport=transport)
    converse_gemini(db, client, '相談', reference_ids=[current], consent=True)
    assert [r['id'] for r in captured[0]['records']] == [current]
    assert other not in [r['id'] for r in captured[0]['records']]
    refs = json.loads(db.rows('SELECT refs FROM responses ORDER BY id DESC')[0]['refs'])
    assert refs[0]['thought'] == '今の立場'
    assert refs[0]['reason'] == '理由'
    for invalid in (old, 999):
        with pytest.raises(ValueError):
            converse_gemini(db, client, '相談', reference_ids=[invalid], consent=True)
    assert len(captured) == 1


@pytest.mark.parametrize('raw', [envelope([999]), envelope(finish='MAX_TOKENS'), b'{}', b'not json', envelope(text='')])
def test_invalid_remote_response_does_not_persist(db, raw):
    client = GeminiResponder('test-key-only', transport=lambda *a, **k: Response(raw))
    with pytest.raises(GeminiError):
        converse_gemini(db, client, '相談', consent=True)
    for table in ('messages', 'responses', 'candidates'):
        assert db.rows(f'SELECT * FROM {table}') == []


@pytest.mark.parametrize('code', [400, 401, 403, 404, 429, 500, 302])
def test_http_errors_are_redacted_without_partial_save(db, code, capsys):
    calls = []
    def fail(req, timeout):
        calls.append(1)
        raise HTTPError(req.full_url, code, 'SECRET INPUT AND KEY', {}, BytesIO(b'SECRET'))
    client = GeminiResponder('test-key-only', transport=fail)
    with pytest.raises(GeminiError) as error:
        converse_gemini(db, client, '相談', consent=True)
    assert 'SECRET' not in str(error.value) and 'test-key-only' not in str(error.value)
    assert len(calls) == 1
    assert not db.rows('SELECT * FROM messages')
    assert capsys.readouterr().out == ''


def test_missing_key_consent_timeout_and_model_validation(db):
    def forbidden(*a, **k):
        raise AssertionError('Must not send')
    for client, consent in [(GeminiResponder('test', transport=forbidden), False),
                            (GeminiResponder('', transport=forbidden), True),
                            (GeminiResponder('test', model='../secret', transport=forbidden), True)]:
        with pytest.raises((ValueError, GeminiError)):
            converse_gemini(db, client, '相談', consent=consent)
    def timeout(*a, **k):
        raise URLError('SECRET')
    with pytest.raises(GeminiError) as error:
        converse_gemini(db, GeminiResponder('test', transport=timeout), '相談', consent=True)
    assert 'SECRET' not in str(error.value)
    assert not db.rows('SELECT * FROM candidates')


def test_history_limit_and_opt_out_and_correction(db):
    captured = []
    def transport(req, timeout):
        captured.append(json.loads(json.loads(req.data)['contents'][0]['parts'][0]['text']))
        return Response(envelope())
    client = GeminiResponder('test-key-only', transport=transport)
    for i in range(12):
        converse_gemini(db, client, f'相談{i}', consent=True)
    assert len(db.gemini_history()) == 20
    assert db.gemini_history()[0]['text'] == '相談2'
    converse_gemini(db, client, 'その解釈は違います', consent=True, include_history=False, correction_of=12)
    assert captured[-1]['history'] == []
    assert captured[-1]['correction_of']['interpretation'] == '話を聞かせてください'
    body = json.loads(db.rows('SELECT body FROM responses ORDER BY id DESC')[0]['body'])
    assert body['correction_of'] == 12
    db.clear_conversations()
    assert db.gemini_history() == []


def test_ui_gemini_requires_confirmation_before_send(tmp_path, monkeypatch):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('SELF_DIALOGUE_DB', str(tmp_path/'ui.sqlite3'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'src/lab.py')).run()
    next(s for s in app.selectbox if s.label == '応答モード').set_value('Geminiチャット').run()
    assert not app.exception
    assert app.chat_input[0].disabled
    assert not any(s.label == 'モックシナリオ' for s in app.selectbox)


@pytest.mark.parametrize('value', ['0', '301', 'nan', 'not-a-number'])
def test_invalid_timeout_is_rejected_before_network(value, monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', value)
    def forbidden(*args, **kwargs):
        raise AssertionError('No request expected')
    with pytest.raises(GeminiError, match='GEMINI_TIMEOUT_SECONDS'):
        GeminiResponder('test', transport=forbidden).respond('test', 'A', [])


def test_timeout_message_is_specific_and_configurable(monkeypatch):
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '90')
    def timeout(req, timeout):
        assert timeout == 90
        raise TimeoutError('secret detail')
    with pytest.raises(GeminiError, match='タイムアウト') as error:
        GeminiResponder('test', transport=timeout).respond('test', 'A', [])
    assert 'secret detail' not in str(error.value)
