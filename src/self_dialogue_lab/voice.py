"""Local, bounded WAV transcription. Audio and drafts are never persisted here."""

from array import array
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
import sys
import wave

MODEL_ID = 'Systran/faster-whisper-small'
MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'
MAX_SECONDS = 60
MAX_BYTES = 16000 * 2 * MAX_SECONDS + 4096


class VoiceError(RuntimeError):
    """Safe user-facing transcription errors."""


def validate_audio(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise VoiceError('録音は60秒以内にして、もう一度録音してください。')
    try:
        with wave.open(BytesIO(data), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('unsupported WAV')
            frames = audio.getnframes()
            if not 0 < frames <= 16000 * MAX_SECONDS:
                raise VoiceError('録音は60秒以内にして、もう一度録音してください。')
            pcm = audio.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError('truncated WAV')
    except VoiceError:
        raise
    except Exception:
        raise VoiceError('録音を読み込めません。マイクで録音し直してください。') from None
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    if max(map(abs, samples)) < 32:
        raise VoiceError('声を確認できませんでした。マイクや音量を確認して録音し直してください。')


@lru_cache(maxsize=1)
def _load_model(path):
    if not Path(path).is_dir():
        raise VoiceError('音声モデルが見つかりません。READMEの音声入力セットアップを実行してください。')
    try:
        from faster_whisper import WhisperModel
        return WhisperModel(path, device='cpu', compute_type='int8', local_files_only=True)
    except Exception:
        raise VoiceError('音声モデルまたは依存を読み込めません。音声入力のセットアップを確認してください。') from None


def transcribe(data, model=None):
    validate_audio(data)
    if model is None:
        path = os.environ.get('VOICE_MODEL_PATH', '').strip()
        if not path:
            raise VoiceError('VOICE_MODEL_PATHが未設定です。READMEの音声入力セットアップを実行してください。')
        model = _load_model(path)
    try:
        segments, _ = model.transcribe(BytesIO(data), language='ja', task='transcribe',
                                       beam_size=5, vad_filter=True, condition_on_previous_text=False)
        # Consume the lazy iterator inside the safe error boundary.
        text = ''.join(segment.text for segment in segments).strip()
        if len(text) > 20000:
            raise ValueError('oversized transcript')
    except Exception:
        raise VoiceError('文字起こしに失敗しました。短く録音し直すか、手入力してください。') from None
    if not text:
        raise VoiceError('言葉を認識できませんでした。録音し直すか、手入力してください。')
    return text


def prepare():
    path = os.environ.get('VOICE_MODEL_PATH', '').strip()
    if not path:
        raise VoiceError('VOICE_MODEL_PATHをモデルの保存先に設定してください。')
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=path,
                          allow_patterns=['config.json', 'model.bin', 'tokenizer.json',
                                          'vocabulary.txt', 'README.md', 'LICENSE*'])
        _load_model.cache_clear()
        _load_model(path)
    except VoiceError:
        raise
    except Exception:
        raise VoiceError('音声モデルを取得できません。通信・依存・保存先を確認してください。') from None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Prepare the optional local voice model')
    parser.add_argument('--prepare', action='store_true', required=True)
    parser.parse_args()
    try:
        prepare()
        print('Local voice model is ready.')
    except VoiceError as error:
        parser.exit(1, str(error) + '\n')
