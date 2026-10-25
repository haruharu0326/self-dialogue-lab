from io import BytesIO
from types import SimpleNamespace
import math
import struct
import wave

import pytest

from self_dialogue_lab.voice import MAX_BYTES, VoiceError, transcribe, validate_audio


def wav(seconds=.1, *, rate=16000, channels=1, silent=False):
    target = BytesIO()
    count = int(rate * seconds)
    pcm = b'\0\0' * count if silent else b''.join(
        struct.pack('<h', int(2000 * math.sin(i * .1))) for i in range(count))
    with wave.open(target, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    return target.getvalue()


def test_voice_passes_only_audio_with_local_transcription_options():
    calls = []
    data = wav()
    class Model:
        def transcribe(self, audio, **options):
            calls.append((audio.read(), options))
            return iter([SimpleNamespace(text=' 今日は'), SimpleNamespace(text='晴れです。 ')]), None
    assert transcribe(data, Model()) == '今日は晴れです。'
    assert calls == [(data, dict(language='ja', task='transcribe', beam_size=5,
                                vad_filter=True, condition_on_previous_text=False))]


@pytest.mark.parametrize('data', [b'', b'invalid', b'x' * (MAX_BYTES + 1), wav(silent=True),
                                  wav(rate=8000), wav(channels=2), wav()[:-10]],
                         ids=['empty', 'invalid', 'oversized', 'silence', 'rate', 'stereo', 'truncated'])
def test_invalid_recording_never_calls_model(data):
    class Model:
        def transcribe(self, *args, **kwargs):
            pytest.fail('invalid audio reached inference')
    with pytest.raises(VoiceError):
        transcribe(data, Model())


def test_duration_boundary():
    validate_audio(wav(60))
    with pytest.raises(VoiceError):
        validate_audio(wav(60.01))


def test_unconfigured_model_is_not_downloaded(monkeypatch):
    monkeypatch.delenv('VOICE_MODEL_PATH', raising=False)
    with pytest.raises(VoiceError, match='VOICE_MODEL_PATH'):
        transcribe(wav())


@pytest.mark.parametrize('mode', ['empty', 'lazy_failure', 'failure', 'oversized'])
def test_transcription_errors_are_safe(mode):
    def segments():
        if mode == 'lazy_failure':
            yield SimpleNamespace(text='途中まで')
            raise RuntimeError('private audio details')
        if mode == 'oversized':
            yield SimpleNamespace(text='x' * 20001)
    class Model:
        def transcribe(self, *args, **kwargs):
            if mode == 'failure':
                raise RuntimeError('private audio details')
            return segments(), None
    with pytest.raises(VoiceError) as error:
        transcribe(wav(), Model())
    assert 'private audio details' not in str(error.value)


def test_local_loader_and_pinned_prepare(tmp_path, monkeypatch):
    import sys
    from self_dialogue_lab import voice
    loaded, downloaded = [], []
    def model(path, **kwargs):
        loaded.append((path, kwargs))
        return object()
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=model))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        snapshot_download=lambda **kwargs: downloaded.append(kwargs)))
    monkeypatch.setenv('VOICE_MODEL_PATH', str(tmp_path))
    voice._load_model.cache_clear()
    try:
        voice.prepare()
        assert downloaded[0]['repo_id'] == voice.MODEL_ID
        assert downloaded[0]['revision'] == voice.MODEL_REVISION
        assert downloaded[0]['allow_patterns'] == ['config.json', 'model.bin', 'tokenizer.json',
                                                 'vocabulary.txt', 'README.md', 'LICENSE*']
        assert loaded == [(str(tmp_path), dict(device='cpu', compute_type='int8', local_files_only=True))]
    finally:
        voice._load_model.cache_clear()
