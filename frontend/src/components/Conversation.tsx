import { useRef, useState } from 'react'
import { messageOf, type Api } from '../api'
import type { Exchange } from '../types'

type Props = {
  exchanges: Exchange[]
  epoch: number
  pending: string | null
  busy: boolean
  toneConfigured: boolean
  tone: Api['tone']
  onApprove: (candidateId: number, thought: string) => void
  onReject: (candidateId: number) => void
}

export function Conversation({ exchanges, epoch, pending, busy, toneConfigured, tone, onApprove, onReject }: Props) {
  if (exchanges.length === 0 && pending === null) {
    return <p className="empty">いま迷っていることや、うまく言葉にならないことから、話してみてください。</p>
  }
  return (
    <ol className="conversation" aria-label="会話">
      {exchanges.map((exchange) => (
        // IDs restart after the conversation is cleared, so the epoch keeps old drafts and tone results from reattaching.
        <li key={`${epoch}:${exchange.id}`} className="exchange">
          <UserTurn exchange={exchange} busy={busy} toneConfigured={toneConfigured} tone={tone} onApprove={onApprove} onReject={onReject} />
          <AssistantTurn exchange={exchange} />
        </li>
      ))}
      {pending !== null && (
        <li className="exchange" aria-busy="true">
          <article className="turn turn-user">
            <p className="visually-hidden">あなた</p>
            <p className="turn-text">{pending}</p>
          </article>
          <article className="turn turn-ai turn-thinking" role="status">
            <span className="thinking-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            考えを整理しています…
          </article>
        </li>
      )}
    </ol>
  )
}

type TurnProps = Pick<Props, 'busy' | 'toneConfigured' | 'tone' | 'onApprove' | 'onReject'> & { exchange: Exchange }

function UserTurn({ exchange, busy, toneConfigured, tone, onApprove, onReject }: TurnProps) {
  const candidate = exchange.candidate
  const [thought, setThought] = useState(candidate?.thought ?? '')
  // Press the stamp only when approved on this page, not for answers already approved on load.
  const approvedOnLoad = useRef(candidate?.status === 'approved')
  return (
    <article className="turn turn-user">
      <p className="visually-hidden">あなた</p>
      <p className="turn-text">{exchange.message}</p>
      {candidate?.status === 'pending' && (
        <details className="fold fold-remember">
          <summary>この回答を覚えておく</summary>
          <form
            className="fold-body"
            onSubmit={(event) => {
              event.preventDefault()
              onApprove(candidate.id, thought)
            }}
          >
            <label className="field">
              <span>覚えておく内容</span>
              <textarea value={thought} rows={3} onChange={(event) => setThought(event.target.value)} />
            </label>
            <p className="note">確認した内容だけ、これからの対話で参照します。</p>
            <div className="actions">
              <button type="submit" className="button button-primary" disabled={busy}>
                覚えておく
              </button>
              <button type="button" className="button button-quiet" disabled={busy} onClick={() => onReject(candidate.id)}>
                今回は覚えない
              </button>
            </div>
          </form>
        </details>
      )}
      {candidate?.status === 'approved' && (
        <div className="saved">
          <span className={approvedOnLoad.current ? 'stamp' : 'stamp is-new'} aria-hidden="true">
            覚えた
          </span>
          <p className="note">保存した回答です。現在の記憶は「覚えていること」で確認できます。</p>
        </div>
      )}
      <Tone exchangeId={exchange.id} configured={toneConfigured} tone={tone} />
    </article>
  )
}

function Tone({ exchangeId, configured, tone }: { exchangeId: number; configured: boolean; tone: Api['tone'] }) {
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const analyze = async () => {
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      setResult((await tone(exchangeId)).label)
    } catch (caught) {
      setError(messageOf(caught))
    } finally {
      setRunning(false)
    }
  }
  return (
    <details className="fold fold-minor">
      <summary>文章のトーン（任意）</summary>
      <div className="fold-body">
        <p className="note">本人の気持ちの断定ではなく、文章からの推定です。中立は「感情がない」という意味ではありません。</p>
        <p className="note">このボタンの分析結果は記憶やGeminiへ渡しません。結果はこの表示だけで、再読み込みや会話の削除で消えます。送信欄でトーン送信を選んだ場合は、送信時に別途分析します。</p>
        {!configured && <p className="note">分析モデルは未設定です。READMEの「文章のトーン分析」の手順で有効化できます。</p>}
        <button type="button" className="button button-quiet" disabled={!configured || running} onClick={analyze}>
          {running ? 'この発言をPC内で分析しています…' : '文章のトーンを分析'}
        </button>
        {error && <p className="alert alert-error" role="alert">{error}</p>}
        {result && (
          <div className="tone-result" role="status">
            <p>文章のトーンの推定：{result}</p>
            <p className="note">長文は先頭512トークンまでが対象です。複数の感情や皮肉を正しく分類できない場合があります。</p>
          </div>
        )}
      </div>
    </details>
  )
}

function AssistantTurn({ exchange }: { exchange: Exchange }) {
  const { reply, refs } = exchange
  return (
    <article className="turn turn-ai">
      <p className="turn-label">{reply.provider === 'gemini' ? 'Geminiの返答（推測を含みます）' : '以前のモック・固定応答'}</p>
      <p className="turn-text">{reply.interpretation}</p>
      {reply.question && <p className="turn-text turn-question">{reply.question}</p>}
      {refs.length > 0 && (
        <details className="fold fold-minor">
          <summary>この返答で参照したこと</summary>
          <div className="fold-body">
            <ul className="refs">
              {refs.map((ref, index) => (
                <li key={index}>{ref.thought}</li>
              ))}
            </ul>
            <p className="note">返答した時点の記録です。後から忘れた内容が当時の会話に残ることがあります。</p>
          </div>
        </details>
      )}
    </article>
  )
}
