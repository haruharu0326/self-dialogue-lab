from io import BytesIO
from pathlib import Path

import pytest

from self_dialogue_lab.responder import Reply
from self_dialogue_lab.store import Store


def product(tmp_path, monkeypatch, *, configured=True, failure=False):
    st = pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    from self_dialogue_lab import ui, voice_ui
    from self_dialogue_lab.gemini import GeminiError
    from self_dialogue_lab.voice import VoiceError
    path = tmp_path / 'personal.sqlite3'
    monkeypatch.setenv('SELF_DIALOGUE_PERSONAL_DB', str(path))
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    if configured:
        monkeypatch.setenv('VOICE_MODEL_PATH', str(tmp_path / 'model'))
    else:
        monkeypatch.delenv('VOICE_MODEL_PATH', raising=False)
    state = {'audio': None, 'calls': [], 'sent': [], 'api_failure': False}
    monkeypatch.setattr(st, 'audio_input', lambda *args, **kwargs: state['audio'])
    def transcribe(data):
        state['calls'].append(data)
        if failure:
            raise VoiceError('文字起こしに失敗しました。')
        return '認識した文章'
    monkeypatch.setattr(voice_ui, 'transcribe', transcribe)
    class Responder:
        model = 'test-adapter'
        def respond(self, message, *args, **kwargs):
            state['sent'].append(message)
            if state['api_failure']:
                raise GeminiError('通信に失敗しました。')
            return Reply('代替応答器の返答', '', [])
    monkeypatch.setattr(ui, 'GeminiResponder', Responder)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src/app.py')).run()
    assert not app.exception
    return app, state, path


def button(app, label):
    return next(b for b in app.button if b.label == label)


def consent(app):
    next(c for c in app.checkbox if c.label == 'この会話と覚えた回答をGeminiへ送信して対話する').check().run()


def test_voice_requires_review_and_consent_and_sends_only_edited_text(tmp_path, monkeypatch):
    app, state, path = product(tmp_path, monkeypatch)
    state['audio'] = BytesIO(b'fake recorded audio')
    app.run()
    assert state['calls'] == [] and state['sent'] == []
    button(app, '文字起こし').click().run()
    assert state['calls'] == [b'fake recorded audio']
    assert button(app, 'この文章を送信').disabled
    db = Store(path)
    assert db.rows('SELECT * FROM messages') == []
    consent(app)
    next(t for t in app.text_area if t.label == '送信する文章（確認・編集）').set_value('編集して確認した文章').run()
    button(app, 'この文章を送信').click().run()
    assert not app.exception
    assert state['sent'] == ['編集して確認した文章']
    assert [r['body'] for r in db.rows('SELECT * FROM messages')] == ['編集して確認した文章']
    assert db.current_records() == []
    assert db.rows('SELECT status FROM candidates')[0]['status'] == 'pending'
    assert app.session_state['voice_epoch'] == 1
    app.run()
    assert state['sent'] == ['編集して確認した文章']
    db.db.close()


def test_recording_change_and_discard_invalidate_previous_draft(tmp_path, monkeypatch):
    app, state, _ = product(tmp_path, monkeypatch)
    state['audio'] = BytesIO(b'first audio')
    app.run()
    button(app, '文字起こし').click().run()
    state['audio'] = BytesIO(b'second audio')
    app.run()
    assert app.text_area[0].value == ''
    button(app, '文字起こし').click().run()
    button(app, '録音と下書きを破棄').click().run()
    assert not app.exception
    assert app.session_state['voice_epoch'] == 1
    assert state['sent'] == []


def test_voice_failure_does_not_create_conversation(tmp_path, monkeypatch):
    app, state, path = product(tmp_path, monkeypatch, failure=True)
    state['audio'] = BytesIO(b'fake audio')
    app.run()
    button(app, '文字起こし').click().run()
    assert not app.exception
    assert any('文字起こしに失敗' in e.value for e in app.error)
    db = Store(path)
    assert db.rows('SELECT * FROM messages') == []
    assert db.current_records() == []
    db.db.close()


def test_api_failure_preserves_voice_draft_and_delete_clears_it(tmp_path, monkeypatch):
    app, state, path = product(tmp_path, monkeypatch)
    consent(app)
    state['audio'] = BytesIO(b'fake audio')
    app.run()
    button(app, '文字起こし').click().run()
    state['api_failure'] = True
    button(app, 'この文章を送信').click().run()
    assert not app.exception
    assert app.text_area[0].value == '認識した文章'
    db = Store(path)
    assert db.rows('SELECT * FROM messages') == []
    state['audio'] = None
    next(c for c in app.checkbox if c.label == '会話履歴を削除してよい').check().run()
    button(app, '会話履歴を削除').click().run()
    assert not app.exception
    assert app.session_state['voice_epoch'] == 1
    db.db.close()


def test_unconfigured_voice_keeps_text_chat_available(tmp_path, monkeypatch):
    app, state, _ = product(tmp_path, monkeypatch, configured=False)
    consent(app)
    assert not app.chat_input[0].disabled
    assert any('音声モデルは未設定' in i.value for i in app.info)
    assert state['calls'] == []
