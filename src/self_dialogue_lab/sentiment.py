"""Optional, local-only sentiment inference. Results are never persisted."""

from functools import lru_cache
import math
import os
from pathlib import Path

MODEL_ID = 'lxyuan/distilbert-base-multilingual-cased-sentiments-student'
MODEL_REVISION = '50406a7df25e4130306d6663e4c9c2ad78093b6e'
LABELS = {'positive': 'ポジティブ', 'neutral': '中立', 'negative': 'ネガティブ'}


class SentimentError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_predictor(path):
    if not Path(path).is_dir():
        raise SentimentError('ローカルのモデルが見つかりません。READMEの事前取得手順を実行してください。')
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline, logging
        logging.set_verbosity_error()
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        model = AutoModelForSequenceClassification.from_pretrained(
            path, local_files_only=True, trust_remote_code=False, use_safetensors=True)
        return pipeline('text-classification', model=model, tokenizer=tokenizer, device=-1)
    except Exception:
        raise SentimentError('分析用の依存またはモデルを読み込めません。任意セットアップを確認してください。') from None


def analyze(text, predictor=None):
    if not text.strip():
        raise SentimentError('分析する発言がありません。')
    if predictor is None:
        path = os.environ.get('SENTIMENT_MODEL_PATH', '')
        if not path:
            raise SentimentError('SENTIMENT_MODEL_PATHが未設定です。')
        predictor = _load_predictor(path)
    try:
        output = predictor(text, truncation=True, max_length=512)[0]
        label = LABELS[output['label'].lower()]
        score = float(output['score'])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('invalid score')
        return {'label': label, 'score': score}
    except Exception:
        raise SentimentError('この発言のトーンを推定できませんでした。') from None


def prepare():
    """Explicit setup only: download public artifacts, never user utterances."""
    path = os.environ.get('SENTIMENT_MODEL_PATH', '')
    if not path:
        raise SentimentError('SENTIMENT_MODEL_PATHを取得先のディレクトリに設定してください。')
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=path,
            allow_patterns=['config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
                            'special_tokens_map.json', 'vocab.txt', 'README.md', 'LICENSE*'],
        )
        _load_predictor.cache_clear()
        _load_predictor(path)
    except SentimentError:
        raise
    except Exception:
        raise SentimentError('モデルを取得できませんでした。依存、通信、保存先を確認してください。') from None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Prepare the optional local sentiment model')
    parser.add_argument('--prepare', action='store_true', required=True)
    parser.parse_args()
    try:
        prepare()
        print('Local sentiment model is ready.')
    except SentimentError as error:
        parser.exit(1, str(error) + '\n')
