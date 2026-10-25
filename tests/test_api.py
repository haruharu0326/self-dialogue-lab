"""Product API boundaries: consent, memory approval, deletion scope and local-only models."""
import json

import pytest
from fastapi.testclient import TestClient

from self_dialogue_lab.api import create_app
from self_dialogue_lab.gemini import GeminiError
from self_dialogue_lab.responder import Reply
from self_dialogue_lab.sentiment import SentimentError
from self_dialogue_lab.store import Store
from self_dialogue_lab.voice import MAX_BYTES, VoiceError


class Responder:
    model = 'test-adapter'
    sent = []
    fail = False

    def respond(self, message, scenario, records, **kwargs):
        Responder.sent.append({'message': message, 'records': records, **kwargs})
        if Responder.fail:
            raise GeminiError('Geminiに接続できませんでした。通信環境を確認して再試行してください。')
        return Reply('代替応答器の返答', 'その理由は何ですか？', records)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ('SENTIMENT_MODEL_PATH', 'VOICE_MODEL_PATH'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    Responder.sent, Responder.fail = [], False
    path = tmp_path / 'personal.sqlite3'
    calls = {'tone': [], 'voice': []}

    def analyzer(text):
        calls['tone'].append(text)
        if text == '失敗する発言':
            raise SentimentError('この発言のトーンを推定できませんでした。')
        return {'label': '中立', 'score': 0.5}

    def transcriber(data):
        calls['voice'].append(data)
        if data == b'bad':
            raise VoiceError('録音を読み込めません。マイクで録音し直してください。')
        return '認識した文章'

    app = create_app(str(path), responder_factory=Responder, analyzer=analyzer, transcriber=transcriber,
                     static_dir=tmp_path / 'missing')
    return TestClient(app, base_url='http://127.0.0.1:8501'), path, calls


def snapshot(path):
    db = Store(path)
    try:
        return {table: db.rows(f'SELECT * FROM {table}') for table in ('records', 'messages', 'responses', 'candidates', 'feedback', 'meta')}
    finally:
        db.db.close()


def send(client, text, consent=True):
    return client.post('/api/messages', json={'text': text, 'consent': consent})


def test_initial_state_is_empty_without_samples(env, monkeypatch):
    client, path, _ = env
    monkeypatch.delenv('GEMINI_API_KEY')
    state = client.get('/api/state').json()
    assert state == {'configured': False, 'voiceConfigured': False, 'toneConfigured': False, 'exchanges': [], 'memories': []}
    assert snapshot(path)['meta'] == [] and snapshot(path)['records'] == []


def test_consent_and_blank_input_are_checked_before_the_model(env):
    client, path, _ = env
    response = send(client, '相談', consent=False)
    assert response.status_code == 400 and '送信確認' in response.json()['detail']
    assert send(client, '   ').status_code == 400
    assert Responder.sent == [] and snapshot(path)['messages'] == []


def test_answer_becomes_memory_only_after_approval_and_only_once(env):
    client, path, _ = env
    state = send(client, '家族との時間を大切にしたい').json()
    exchange = state['exchanges'][0]
    assert exchange['candidate']['status'] == 'pending' and state['memories'] == []
    assert exchange['reply'] == {'provider': 'gemini', 'interpretation': '代替応答器の返答', 'question': 'その理由は何ですか？'}
    assert Responder.sent[-1]['records'] == []

    blank = client.post(f"/api/candidates/{exchange['candidate']['id']}/approve", json={'thought': ' '})
    assert blank.status_code == 400 and blank.json()['detail'] == '考えを入力してください'
    state = client.post(f"/api/candidates/{exchange['candidate']['id']}/approve", json={'thought': ' 家族の時間 '}).json()
    assert [m['thought'] for m in state['memories']] == ['家族の時間']
    assert state['exchanges'][0]['candidate']['status'] == 'approved'
    again = client.post(f"/api/candidates/{exchange['candidate']['id']}/approve", json={'thought': '二重'})
    assert again.status_code == 400 and len(snapshot(path)['records']) == 1

    state = send(client, '転職について').json()
    assert [r['thought'] for r in Responder.sent[-1]['records']] == ['家族の時間']
    assert state['exchanges'][1]['refs'] == [{'thought': '家族の時間'}]


def test_rejected_and_forgotten_answers_leave_long_term_context(env):
    client, path, _ = env
    first = send(client, 'まだ仮の考えです').json()['exchanges'][0]['candidate']['id']
    state = client.post(f'/api/candidates/{first}/reject').json()
    assert state['exchanges'][0]['candidate']['status'] == 'rejected'
    assert client.post(f'/api/candidates/{first}/reject').status_code == 400
    assert client.post(f'/api/candidates/{first}/approve', json={'thought': '後から'}).status_code == 400

    second = send(client, '覚える話').json()['exchanges'][1]['candidate']['id']
    memory = client.post(f'/api/candidates/{second}/approve', json={'thought': '覚える話'}).json()['memories'][0]['id']
    state = client.delete(f'/api/memories/{memory}').json()
    assert state['memories'] == [] and len(state['exchanges']) == 2
    assert client.delete(f'/api/memories/{memory}').status_code == 400
    send(client, '今の考え')
    assert Responder.sent[-1]['records'] == []
    assert Responder.sent[-1]['history'][0]['text'] == 'まだ仮の考えです'


def test_clearing_conversation_keeps_memories(env):
    client, path, _ = env
    candidate = send(client, '残す回答').json()['exchanges'][0]['candidate']['id']
    client.post(f'/api/candidates/{candidate}/approve', json={'thought': '残す回答'})
    state = client.delete('/api/conversations').json()
    assert state['exchanges'] == [] and [m['thought'] for m in state['memories']] == ['残す回答']
    data = snapshot(path)
    assert data['messages'] == data['responses'] == data['candidates'] == []
    assert send(client, '次の会話').status_code == 200


def test_api_failure_is_redacted_and_saves_nothing(env):
    client, path, _ = env
    Responder.fail = True
    response = send(client, '失敗する相談')
    assert response.status_code == 502
    assert response.json()['detail'] == 'Geminiに接続できませんでした。通信環境を確認して再試行してください。'
    assert snapshot(path)['messages'] == [] and snapshot(path)['candidates'] == []


def test_legacy_mock_replies_are_labelled_as_mock(env):
    client, path, _ = env
    db = Store(path)
    with db.transaction():
        mid = db.db.execute("INSERT INTO messages(role,body) VALUES('user','以前の発言')").lastrowid
        db.db.execute('INSERT INTO responses(message_id,body,refs) VALUES(?,?,?)',
                      (mid, json.dumps({'interpretation': '固定文', 'question': ''}), '[]'))
    db.db.close()
    exchange = client.get('/api/state').json()['exchanges'][0]
    assert exchange['reply']['provider'] == 'mock' and exchange['candidate'] is None


def test_storage_errors_use_safe_messages(env, tmp_path):
    client, path, _ = env
    send(client, '壊す前の発言')
    db = Store(path)
    db.write("UPDATE responses SET body='not json'")
    db.db.close()
    response = client.get('/api/state')
    assert response.status_code == 500 and response.json()['detail'] == '保存データの形式を確認してください。'

    blocked = tmp_path / 'file'
    blocked.write_text('x')
    broken = TestClient(create_app(str(blocked / 'db.sqlite3'), static_dir=tmp_path / 'missing'), base_url='http://127.0.0.1')
    response = broken.get('/api/state')
    assert response.status_code == 500 and response.json()['detail'].startswith('保存データにアクセスできません')


def test_tone_is_manual_ephemeral_and_does_not_modify_storage(env, monkeypatch):
    client, path, calls = env
    response_id = send(client, '今日は少し疲れた').json()['exchanges'][0]['id']
    before = snapshot(path)
    unconfigured = client.post(f'/api/exchanges/{response_id}/tone')
    assert unconfigured.status_code == 422 and calls['tone'] == []

    monkeypatch.setenv('SENTIMENT_MODEL_PATH', 'model')
    assert client.get('/api/state').json()['toneConfigured'] is True
    assert calls['tone'] == []
    assert client.post(f'/api/exchanges/{response_id}/tone').json() == {'label': '中立'}
    assert calls['tone'] == ['今日は少し疲れた']
    assert client.post('/api/exchanges/999/tone').status_code == 400
    assert snapshot(path) == before
    assert '中立' not in json.dumps(client.get('/api/state').json(), ensure_ascii=False)

    failing = send(client, '失敗する発言').json()['exchanges'][1]['id']
    response = client.post(f'/api/exchanges/{failing}/tone')
    assert response.status_code == 422 and response.json()['detail'] == 'この発言のトーンを推定できませんでした。'


def test_voice_transcription_never_sends_or_stores(env, monkeypatch):
    client, path, calls = env
    headers = {'content-type': 'audio/wav'}
    assert client.post('/api/voice/transcribe', content=b'wav', headers=headers).status_code == 422
    monkeypatch.setenv('VOICE_MODEL_PATH', 'model')
    assert client.get('/api/state').json()['voiceConfigured'] is True

    response = client.post('/api/voice/transcribe', content=b'wav', headers=headers)
    assert response.json() == {'text': '認識した文章'} and calls['voice'] == [b'wav']
    assert Responder.sent == [] and snapshot(path)['messages'] == []

    assert client.post('/api/voice/transcribe', content=b'wav', headers={'content-type': 'audio/webm'}).status_code == 422
    too_long = client.post('/api/voice/transcribe', content=b'0' * (MAX_BYTES + 1), headers=headers)
    assert too_long.status_code == 422 and '60秒' in too_long.json()['detail']
    failed = client.post('/api/voice/transcribe', content=b'bad', headers=headers)
    assert failed.status_code == 422 and failed.json()['detail'].startswith('録音を読み込めません')
    assert len(calls['voice']) == 2


def test_only_local_browser_requests_are_accepted(env):
    client, path, _ = env
    assert client.get('/api/state', headers={'host': 'evil.example:8501'}).status_code == 403
    cross = client.delete('/api/conversations', headers={'origin': 'http://evil.example'})
    assert cross.status_code == 403
    same = client.delete('/api/conversations', headers={'origin': 'http://127.0.0.1:8501'})
    assert same.status_code == 200
    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/media/landscape.png').status_code == 404
    assert '画面がまだビルドされていません' in client.get('/').text
