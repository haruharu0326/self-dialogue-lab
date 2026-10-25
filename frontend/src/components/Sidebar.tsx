import { useState } from 'react'
import type { Memory } from '../types'

type Props = {
  configured: boolean
  memories: Memory[]
  busy: boolean
  onResetConsent: () => void
  onForget: (id: number) => void
  onClear: () => void
}

export function Sidebar({ configured, memories, busy, onResetConsent, onForget, onClear }: Props) {
  const [clearConfirmed, setClearConfirmed] = useState(false)
  return (
    <div className="sidebar-inner">
      <p className="wordmark" aria-hidden="true">
        Self Dialogue Lab
      </p>

      <details className="panel" open={!configured}>
        <summary>接続と送信について</summary>
        <div className="panel-body">
          <p>Geminiへ、この会話の直近10往復と、あなたが覚えておくと決めた現在の記録を送ります。画像やAPIキーを会話本文には含めません。</p>
          <p className="note">「覚える」は保存した回答を次回に参照する方式です。モデルを再訓練するものではありません。</p>
          {!configured && (
            <>
              <p>ローカルの.envにGEMINI_API_KEYを設定し、Dockerを再作成してください。キーをチャットに貼らないでください。</p>
              <a className="button button-quiet" href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
                GeminiのAPIキーを設定する
              </a>
            </>
          )}
          <button type="button" className="button button-quiet" onClick={onResetConsent}>
            送信の確認をやり直す
          </button>
        </div>
      </details>

      <details className="panel">
        <summary>覚えていること（{memories.length}件）</summary>
        <div className="panel-body">
          {memories.length === 0 && <p className="note">まだありません。会話の中の「この回答を覚えておく」から残せます。</p>}
          <ul className="memory-list">
            {memories.map((memory) => (
              <MemoryItem key={memory.id} memory={memory} busy={busy} onForget={onForget} />
            ))}
          </ul>
        </div>
      </details>

      <details className="panel">
        <summary>会話を消す</summary>
        <div className="panel-body">
          <p className="note">会話を消しても、覚えた回答は残ります。元には戻せません。</p>
          <label className="check">
            <input type="checkbox" checked={clearConfirmed} onChange={(event) => setClearConfirmed(event.target.checked)} />
            会話履歴を削除してよい
          </label>
          <button
            type="button"
            className="button button-danger"
            disabled={!clearConfirmed || busy}
            onClick={() => {
              setClearConfirmed(false)
              onClear()
            }}
          >
            会話履歴を削除
          </button>
        </div>
      </details>
    </div>
  )
}

function MemoryItem({ memory, busy, onForget }: { memory: Memory; busy: boolean; onForget: (id: number) => void }) {
  const [confirmed, setConfirmed] = useState(false)
  return (
    <li className="memory">
      <p className="memory-thought">{memory.thought}</p>
      <p className="note">忘れても、当時の会話は残ります。次回の返答の参照対象からは外れます。</p>
      <div className="memory-actions">
        <label className="check">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          この内容を忘れてよい
        </label>
        <button type="button" className="button button-quiet" disabled={!confirmed || busy} onClick={() => onForget(memory.id)}>
          忘れる
        </button>
      </div>
    </li>
  )
}
