import pytest

from self_dialogue_lab.sentiment import analyze, SentimentError


def test_sentiment_is_optional_and_no_heuristic_fallback(monkeypatch):
    monkeypatch.delenv('SENTIMENT_MODEL_PATH', raising=False)
    with pytest.raises(SentimentError):
        analyze('嬉しいです')


def test_sentiment_adapter_passes_only_text_and_returns_uncertain_label():
    calls = []
    def predictor(text, **kwargs):
        calls.append((text, kwargs))
        return [{'label': 'neutral', 'score': .62}]
    result = analyze('複雑な気持ちです', predictor=predictor)
    assert result == {'label': '中立', 'score': .62}
    assert calls == [('複雑な気持ちです', {'truncation': True, 'max_length': 512})]
    # 代替分類器で入出力境界だけを確認。実モデルの日本語精度のテストではない。


@pytest.mark.parametrize('output', [[{'label': 'unknown', 'score': .9}],
                                   [{'label': 'positive', 'score': float('nan')}],
                                   [{'label': 'negative', 'score': 2}], []])
def test_sentiment_rejects_invalid_output(output):
    with pytest.raises(SentimentError):
        analyze('発言', predictor=lambda *a, **k: output)
