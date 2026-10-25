from pathlib import Path

import pytest

from self_dialogue_lab.service import converse_personal
from self_dialogue_lab.store import Store
from self_dialogue_lab.responder import Reply


class SampleResponder:
    model = 'test-adapter'

    def respond(self, *args, **kwargs):
        return Reply('テスト用の返答', '', [])


@pytest.mark.parametrize('mode', ['unconfigured', 'success', 'failure'])
def test_product_tone_is_manual_ephemeral_and_does_not_modify_storage(tmp_path, monkeypatch, mode):
    pytest.importorskip('streamlit')
    from streamlit.testing.v1 import AppTest
    from self_dialogue_lab import sentiment_ui
    from self_dialogue_lab.sentiment import SentimentError

    path = tmp_path / 'personal.sqlite3'
    monkeypatch.setenv('SELF_DIALOGUE_PERSONAL_DB', str(path))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    if mode == 'unconfigured':
        monkeypatch.delenv('SENTIMENT_MODEL_PATH', raising=False)
    else:
        monkeypatch.setenv('SENTIMENT_MODEL_PATH', str(tmp_path / 'model'))
    db = Store(path)
    converse_personal(db, SampleResponder(), '今日は嬉しいです', consent=True)
    before = list(db.db.iterdump())
    calls = []

    def analyze(text):
        calls.append(text)
        if mode == 'failure':
            raise SentimentError('この発言のトーンを推定できませんでした。')
        return {'label': 'ポジティブ', 'score': .8}

    monkeypatch.setattr(sentiment_ui, 'analyze', analyze)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'src/app.py')).run()
    assert not app.exception
    assert calls == []
    button = app.button(key='product_tone_1')
    assert button.disabled == (mode == 'unconfigured')
    assert any('本人の気持ちの断定ではなく' in c.value for c in app.caption)
    if mode != 'unconfigured':
        button.click().run()
        assert not app.exception
        assert calls == ['今日は嬉しいです']
        if mode == 'success':
            assert any('文章のトーンの推定：ポジティブ' in m.value for m in app.markdown)
        else:
            assert any('推定できませんでした' in e.value for e in app.error)
        app.run()
        assert calls == ['今日は嬉しいです']
        assert not any('文章のトーンの推定：' in m.value for m in app.markdown)
    assert list(db.db.iterdump()) == before
    # Deletion and reused response IDs must not redisplay a prior result.
    db.clear_conversations()
    converse_personal(db, SampleResponder(), '別の発言', consent=True)
    app.run()
    assert not app.exception
    assert not any('文章のトーンの推定：' in m.value for m in app.markdown)
    assert all('別の発言' != text for text in calls)
    db.db.close()
