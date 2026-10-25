import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { api as defaultApi, messageOf, type Api } from './api'
import { Conversation } from './components/Conversation'
import { Sidebar } from './components/Sidebar'
import { VoiceInput } from './components/VoiceInput'
import { browserRecorder, type Recorder } from './recorder'
import type { AppState } from './types'

type Props = { api?: Api; recorder?: Recorder }

export default function App({ api = defaultApi, recorder = browserRecorder }: Props) {
  const [state, setState] = useState<AppState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  // Consent lives only in this page's memory, like the former Streamlit session.
  const [consent, setConsent] = useState(false)
  const [includeTone, setIncludeTone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [epoch, setEpoch] = useState(0)
  const [text, setText] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const end = useRef<HTMLDivElement>(null)

  const load = () => {
    setLoadError(null)
    api.state().then(setState, (caught) => setLoadError(messageOf(caught)))
  }
  useEffect(load, [api])
  // Jump to the latest turn on first load; glide only for turns added while the page is open.
  const scrolled = useRef(false)
  useEffect(() => {
    if (!state) return
    end.current?.scrollIntoView?.({ behavior: scrolled.current ? 'smooth' : 'auto', block: 'end' })
    scrolled.current = true
  }, [state?.exchanges.length, pending])

  const run = async (action: () => Promise<AppState>, success?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const next = await action()
      // Same synchronous block, so the pending bubble and the saved exchange never render together.
      setPending(null)
      setState(next)
      if (success) setNotice(success)
      return true
    } catch (caught) {
      setPending(null)
      setError(messageOf(caught))
      return false
    } finally {
      setBusy(false)
    }
  }

  const send = (message: string) => {
    setPending(message)
    return run(() => includeTone ? api.send(message, consent, true) : api.send(message, consent))
  }

  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    if (busy || !text.trim()) return
    if (await send(text)) setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter breaks the line; never send while an IME is composing.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void submit()
    }
  }

  if (!state) {
    return (
      <div className="app app-loading">
        <main className="loading-card">
          <p className="wordmark">Self Dialogue Lab</p>
          {loadError ? (
            <>
              <p className="alert alert-error" role="alert">{loadError}</p>
              <button type="button" className="button button-primary" onClick={load}>
                もう一度読み込む
              </button>
            </>
          ) : (
            <p role="status">読み込んでいます…</p>
          )}
        </main>
      </div>
    )
  }

  const canSend = state.configured && consent
  return (
    <div className="app">
      <aside id="sidebar" className={menuOpen ? 'sidebar is-open' : 'sidebar'} aria-label="記憶と設定">
        <Sidebar
          configured={state.configured}
          memories={state.memories}
          busy={busy}
          onResetConsent={() => { setConsent(false); setIncludeTone(false) }}
          onForget={(id) => run(() => api.forget(id), 'この内容を記憶から外しました。')}
          onClear={async () => {
            if (await run(api.clear, '会話履歴を削除しました。覚えた回答は残っています。')) setEpoch((value) => value + 1)
          }}
        />
      </aside>
      {menuOpen && <button type="button" className="scrim" aria-label="メニューを閉じる" onClick={() => setMenuOpen(false)} />}

      <main className="main">
        <header className="hero">
          <button
            type="button"
            className="menu-button"
            aria-expanded={menuOpen}
            aria-controls="sidebar"
            onClick={() => setMenuOpen((open) => !open)}
          >
            記憶と設定
          </button>
          <h1>話しながら、自分の考えを見つける。</h1>
          <p className="lede">答えを急がず、ひとつずつ。覚えておいてほしい回答だけ、残せます。</p>
        </header>

        <section className="thread" aria-label="対話">
          {!state.configured && (
            <p className="alert alert-info">Geminiの接続設定が必要です。「記憶と設定」の「接続と送信について」から設定できます。</p>
          )}
          {!consent && (
            <label className="consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span>この会話と覚えた回答をGeminiへ送信して対話する</span>
            </label>
          )}
          <Conversation
            exchanges={state.exchanges}
            epoch={epoch}
            pending={pending}
            busy={busy}
            toneConfigured={state.toneConfigured}
            tone={api.tone}
            onApprove={(id, thought) => run(() => api.approve(id, thought), '覚えました。これからの対話で参考にします。')}
            onReject={(id) => run(() => api.reject(id), '会話だけを残し、記憶には追加しませんでした。')}
          />
        </section>

        <footer className="dock">
          <div className="status" aria-live="polite">
            {notice && <p className="alert alert-success">{notice}</p>}
            {error && <p className="alert alert-error" role="alert">{error}</p>}
          </div>
          <VoiceInput key={epoch} configured={state.voiceConfigured} enabled={canSend} recorder={recorder} transcribe={api.transcribe} onSend={send} />
          <label className="consent">
            <input type="checkbox" checked={includeTone} disabled={!state.toneConfigured || busy} onChange={(event) => setIncludeTone(event.target.checked)} />
            <span>送信する文章のトーンもGeminiへ渡す</span>
          </label>
          <p className="note">選択時は送信する文章をPC内で分析し、推定分類とスコアをGoogleへ送ります。本人の気持ちや声色の断定ではありません。分析結果自体は保存しませんが、返答に反映された表現は会話に残ります。{!state.toneConfigured && '分析モデルは未設定です。'}</p>
          <form className="composer" onSubmit={submit}>
            <label className="visually-hidden" htmlFor="message">
              メッセージ
            </label>
            <textarea
              id="message"
              rows={1}
              value={text}
              placeholder="いま、どんなことを考えていますか？"
              disabled={!canSend}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={onKeyDown}
            />
            <button type="submit" className="button button-primary send" disabled={!canSend || busy || !text.trim()}>
              送信
            </button>
          </form>
          <p className="composer-hint">Enterで送信、Shift+Enterで改行</p>
        </footer>
        {/* Below the sticky dock, so scrolling here leaves the latest turn visible above it. */}
        <div ref={end} />
      </main>
    </div>
  )
}
