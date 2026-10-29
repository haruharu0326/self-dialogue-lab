import { useEffect, useRef, useState } from 'react'
import { messageOf, type Api } from '../api'
import { MAX_SECONDS, RecorderError, type Recorder, type Recording } from '../recorder'

type Props = {
  configured: boolean
  enabled: boolean
  /** Another request (typed send, approve, delete…) is in flight; sending is blocked but recording is not. */
  busy: boolean
  recorder: Recorder
  transcribe: Api['transcribe']
  onSend: (text: string) => Promise<boolean>
}

/** Record, transcribe locally, review, then explicitly send. Remount (change key) to discard everything. */
export function VoiceInput({ configured, enabled, busy, recorder, transcribe, onSend }: Props) {
  const [recording, setRecording] = useState<Recording | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [audio, setAudio] = useState<Blob | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [working, setWorking] = useState<'transcribe' | 'send' | null>(null)
  const sendingRef = useRef(false)
  const stopRef = useRef<() => void>(() => {})
  const url = useObjectUrl(audio)

  useEffect(() => {
    if (!recording) return
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 250)
    return () => window.clearInterval(timer)
  }, [recording])
  // Release the microphone if the panel is discarded mid-recording; stop() must not be cancelled.
  const recordingRef = useRef<Recording | null>(null)
  recordingRef.current = recording
  useEffect(() => () => recordingRef.current?.cancel(), [])

  const reset = () => {
    setAudio(null)
    setDraft('')
    setError(null)
  }

  const start = async () => {
    reset()
    setElapsed(0)
    try {
      setRecording(await recorder(() => stopRef.current()))
    } catch (caught) {
      setError(caught instanceof RecorderError ? caught.message : '録音を始められませんでした。')
    }
  }

  const stop = async () => {
    if (!recording) return
    const current = recording
    setRecording(null)
    try {
      setAudio(await current.stop())
    } catch (caught) {
      setError(caught instanceof RecorderError ? caught.message : '録音を読み込めません。マイクで録音し直してください。')
    }
  }
  stopRef.current = stop

  const runTranscribe = async () => {
    if (!audio) return
    setWorking('transcribe')
    setError(null)
    try {
      setDraft((await transcribe(audio)).text)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setWorking(null)
    }
  }

  const send = async () => {
    // Same-frame double click: the second call must not touch `working` of the first.
    if (sendingRef.current) return
    sendingRef.current = true
    setWorking('send')
    let sent = false
    try {
      sent = await onSend(draft.trim())
    } finally {
      sendingRef.current = false
      setWorking(null)
    }
    // A failed send keeps the draft so nothing typed is lost; success is reset by the parent.
    if (sent) reset()
  }

  return (
    <details className="fold fold-voice">
      <summary>音声で入力（任意）</summary>
      <div className="fold-body">
        <p className="note">{MAX_SECONDS}秒以内の日本語を録音できます。音声はこのPC内で文字起こしし、ファイルやDBに保存しません。</p>
        <p className="note">文字起こしには誤りがあります。内容を確認・編集してから送信してください。送信した文章は通常の会話として保存し、Geminiへ送ります。</p>
        {!configured && <p className="alert alert-info">音声モデルは未設定です。READMEの「音声入力」の手順で有効化できます。手入力は引き続き使えます。</p>}
        <div className="actions">
          {recording ? (
            <button type="button" className="button button-record is-recording" onClick={stop}>
              <span className="rec-dot" aria-hidden="true" />
              録音を止める（{elapsed}秒 / {MAX_SECONDS}秒）
            </button>
          ) : (
            <button type="button" className="button button-record" disabled={!configured || working !== null} onClick={start}>
              <span className="rec-dot" aria-hidden="true" />
              {audio ? '録音し直す' : '録音する'}
            </button>
          )}
          {audio && (
            <button type="button" className="button button-quiet" disabled={working !== null} onClick={runTranscribe}>
              {working === 'transcribe' ? 'このPC内で文字起こししています…' : '文字起こし'}
            </button>
          )}
        </div>
        {url && <audio className="playback" controls src={url} aria-label="録音した音声" />}
        {error && <p className="alert alert-error" role="alert">{error}</p>}
        {audio && (
          <>
            <label className="field">
              <span>送信する文章（確認・編集）</span>
              <textarea value={draft} rows={3} onChange={(event) => setDraft(event.target.value)} />
            </label>
            {!enabled && <p className="note">送信にはGeminiの接続設定と、会話の送信確認が必要です。</p>}
            {enabled && busy && working !== 'send' && <p className="note">処理中です。完了するまで送信できません。</p>}
            <div className="actions">
              <button type="button" className="button button-primary" disabled={!enabled || busy || !draft.trim() || working !== null} onClick={send}>
                この文章を送信
              </button>
              <button type="button" className="button button-quiet" disabled={working !== null} onClick={reset}>
                録音と下書きを破棄
              </button>
            </div>
          </>
        )}
      </div>
    </details>
  )
}

function useObjectUrl(blob: Blob | null) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!blob || typeof URL.createObjectURL !== 'function') return setUrl(null)
    const created = URL.createObjectURL(blob)
    setUrl(created)
    return () => URL.revokeObjectURL(created)
  }, [blob])
  return url
}
