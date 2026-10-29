"""HTTP API for the React product screen. Business rules stay in service and store."""

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import sqlite3

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .gemini import GeminiError, GeminiResponder
from .responder import ResponderError
from .sentiment import SentimentError, analyze
from .service import converse_personal
from .store import Store
from .voice import MAX_BYTES, VoiceError, transcribe as local_transcribe

PACKAGE = Path(__file__).parent
STATIC = PACKAGE / 'static'
ALLOWED_HOSTS = {'127.0.0.1', 'localhost'}
STORAGE_ERROR = '保存データにアクセスできません。保存先と起動状態を確認して、もう一度開いてください。'
FORMAT_ERROR = '保存データの形式を確認してください。'


class StorageFormatError(RuntimeError):
    """Stored JSON could not be read; never echo parser details to the screen."""


class Message(BaseModel):
    text: str
    consent: bool = False
    include_tone: bool = False


class Approval(BaseModel):
    thought: str


def _configured(name):
    return bool(os.environ.get(name, '').strip())


def _default_path():
    root = PACKAGE.parents[1]
    return os.environ.get('SELF_DIALOGUE_PERSONAL_DB') or str(root / 'data' / 'personal.sqlite3')


def _exchanges(store):
    try:
        rows = store.rows('SELECT r.*,m.body AS source FROM responses r JOIN messages m ON m.id=r.message_id ORDER BY r.id')
        candidates = {c['message_id']: c for c in store.rows('SELECT * FROM candidates ORDER BY id DESC')}
        exchanges = []
        for row in rows:
            body = json.loads(row['body'])
            candidate = candidates.get(row['message_id'])
            exchanges.append({
                'id': row['id'],
                'message': row['source'],
                'candidate': candidate and {'id': candidate['id'], 'status': candidate['status'], 'thought': candidate['thought']},
                # 生成元は保存時のresponder.provider。旧データの省略はmock扱い。
                'reply': {'provider': body.get('provider') if isinstance(body.get('provider'), str) and body['provider'] else 'mock',
                          'interpretation': body['interpretation'], 'question': body['question']},
                'refs': [{'thought': ref['thought']} for ref in json.loads(row['refs'])],
            })
        return exchanges
    except (ValueError, KeyError, TypeError):
        raise StorageFormatError from None


def _state(store):
    return {
        'configured': _configured('GEMINI_API_KEY'),
        'voiceConfigured': _configured('VOICE_MODEL_PATH'),
        'toneConfigured': _configured('SENTIMENT_MODEL_PATH'),
        'exchanges': _exchanges(store),
        'memories': [{'id': r['id'], 'thought': r['thought'], 'occurred': r['occurred']} for r in store.current_records()],
    }


def _detail(status, message):
    return JSONResponse({'detail': message}, status_code=status)


def create_app(db_path=None, *, responder_factory=None, transcriber=None, analyzer=None, static_dir=STATIC):
    """Dependencies are injectable so tests never touch real models or the network."""
    app = FastAPI(title='Self Dialogue Lab', docs_url=None, redoc_url=None, openapi_url=None)

    @contextmanager
    def opened():
        store = Store(db_path or _default_path())
        try:
            yield store
        finally:
            store.db.close()

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        # Local single-user app: refuse DNS rebinding and cross-site writes.
        host = (request.headers.get('host') or '').rsplit(':', 1)[0].strip('[]')
        if host not in ALLOWED_HOSTS:
            return _detail(403, 'このアプリは同じPCのブラウザから開いてください。')
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD') and origin and urlsplit(origin).netloc != request.headers.get('host'):
            return _detail(403, '別のサイトからの操作は受け付けません。')
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return _detail(400, str(error))

    @app.exception_handler(GeminiError)
    @app.exception_handler(ResponderError)
    async def gemini_failed(request, error):
        return _detail(502, str(error))

    @app.exception_handler(SentimentError)
    @app.exception_handler(VoiceError)
    async def local_model_failed(request, error):
        return _detail(422, str(error))

    @app.exception_handler(StorageFormatError)
    async def storage_format(request, error):
        return _detail(500, FORMAT_ERROR)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_failed(request, error):
        return _detail(500, STORAGE_ERROR)

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/state')
    def state():
        with opened() as store:
            return _state(store)

    @app.post('/api/messages')
    def send(message: Message):
        if not message.consent:
            raise ValueError('Googleへ送信する情報を確認して、送信確認にチェックしてください。')
        if not message.text.strip():
            raise ValueError('メッセージを入力してください')
        tone_context = None
        if message.include_tone:
            if not _configured('SENTIMENT_MODEL_PATH'):
                raise SentimentError('分析モデルは未設定です。トーン送信を解除するか、モデルを設定してください。')
            tone_context = (analyzer or analyze)(message.text)
        with opened() as store:
            responder = (responder_factory or GeminiResponder)()
            converse_personal(store, responder, message.text, consent=message.consent, tone_context=tone_context)
            return _state(store)

    @app.post('/api/candidates/{id}/approve')
    def approve(id: int, approval: Approval):
        with opened() as store:
            store.approve(id, approval.thought, '', '本人が対話中に確認した回答')
            return _state(store)

    @app.post('/api/candidates/{id}/reject')
    def reject(id: int):
        with opened() as store:
            store.reject(id)
            return _state(store)

    @app.delete('/api/memories/{id}')
    def forget(id: int):
        with opened() as store:
            store.delete_record(id)
            return _state(store)

    @app.delete('/api/conversations')
    def clear():
        with opened() as store:
            store.clear_conversations()
            return _state(store)

    @app.post('/api/exchanges/{id}/tone')
    def tone(id: int):
        # The result is returned once and never stored or sent to Gemini.
        if not _configured('SENTIMENT_MODEL_PATH'):
            raise SentimentError('分析モデルは未設定です。READMEの「文章のトーン分析」の手順で有効化できます。')
        with opened() as store:
            rows = store.rows('SELECT m.body FROM responses r JOIN messages m ON m.id=r.message_id WHERE r.id=?', (id,))
        if not rows:
            raise ValueError('分析する発言が見つかりません。')
        result = (analyzer or analyze)(rows[0]['body'])
        return {'label': result['label']}

    @app.post('/api/voice/transcribe')
    async def transcribe(request: Request):
        # Audio stays in memory for this request only; it is never written to disk or the DB.
        if not _configured('VOICE_MODEL_PATH'):
            raise VoiceError('音声モデルは未設定です。READMEの「音声入力」の手順で有効化できます。')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'audio/wav':
            raise VoiceError('録音を読み込めません。マイクで録音し直してください。')
        if int(request.headers.get('content-length') or 0) > MAX_BYTES:
            raise VoiceError('録音は60秒以内にして、もう一度録音してください。')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise VoiceError('録音は60秒以内にして、もう一度録音してください。')
        return {'text': await run_in_threadpool(transcriber or local_transcribe, bytes(data))}

    if (Path(static_dir) / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='screen')
    else:
        @app.get('/', include_in_schema=False)
        def unbuilt():
            return HTMLResponse('<!doctype html><meta charset="utf-8"><title>Self Dialogue Lab</title>'
                                '<p>画面がまだビルドされていません。READMEの手順で <code>npm --prefix frontend run build</code> を実行してください。</p>')

    return app
