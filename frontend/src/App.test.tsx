import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError, type Api } from './api'
import type { Recorder } from './recorder'
import type { AppState, Exchange } from './types'

const exchange = (id: number, message: string, status: 'pending' | 'approved' | 'rejected' = 'pending'): Exchange => ({
  id,
  message,
  candidate: { id, status, thought: message },
  reply: { provider: 'gemini', interpretation: `返答${id}`, question: `問い${id}` },
  refs: [],
})

const base = (overrides: Partial<AppState> = {}): AppState => ({
  configured: true,
  voiceConfigured: false,
  toneConfigured: false,
  exchanges: [],
  memories: [],
  ...overrides,
})

function fakeApi(initial: AppState, overrides: Partial<Api> = {}) {
  let state = initial
  const respond = (next: AppState) => {
    state = next
    return Promise.resolve(state)
  }
  const api: Api = {
    state: vi.fn(() => Promise.resolve(state)),
    send: vi.fn((text: string) => respond({ ...state, exchanges: [...state.exchanges, exchange(state.exchanges.length + 1, text)] })),
    approve: vi.fn((id: number, thought: string) =>
      respond({
        ...state,
        exchanges: state.exchanges.map((e) => (e.candidate?.id === id ? { ...e, candidate: { ...e.candidate, status: 'approved' } } : e)),
        memories: [{ id: 1, thought, occurred: '2026-10-25T10:00' }],
      }),
    ),
    reject: vi.fn((id: number) =>
      respond({ ...state, exchanges: state.exchanges.map((e) => (e.candidate?.id === id ? { ...e, candidate: { ...e.candidate, status: 'rejected' } } : e)) }),
    ),
    forget: vi.fn((id: number) => respond({ ...state, memories: state.memories.filter((m) => m.id !== id) })),
    clear: vi.fn(() => respond({ ...state, exchanges: [] })),
    tone: vi.fn(() => Promise.resolve({ label: '中立' })),
    transcribe: vi.fn(() => Promise.resolve({ text: '認識した文章' })),
    ...overrides,
  }
  return api
}

const messageBox = () => screen.getByRole('textbox', { name: 'メッセージ' })
const consent = () => userEvent.click(screen.getByRole('checkbox', { name: 'この会話と覚えた回答をGeminiへ送信して対話する' }))

describe('product screen', () => {
  it('shows only the conversation, without lab controls or samples, and blocks input without a key', async () => {
    const api = fakeApi(base({ configured: false }))
    render(<App api={api} />)
    expect(await screen.findByText('いま迷っていることや、うまく言葉にならないことから、話してみてください。')).toBeInTheDocument()
    expect(screen.getByText(/Geminiの接続設定が必要です/)).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.queryByRole('radio')).toBeNull()
    expect(screen.queryByText(/シナリオ/)).toBeNull()
    await consent()
    expect(messageBox()).toBeDisabled()
    expect(screen.getByRole('link', { name: 'GeminiのAPIキーを設定する' })).toHaveAttribute('href', 'https://aistudio.google.com/apikey')
  })

  it('requires consent before sending and keeps the text when sending fails', async () => {
    const api = fakeApi(base(), { send: vi.fn(() => Promise.reject(new ApiError('Geminiに接続できませんでした。'))) })
    render(<App api={api} />)
    await screen.findByText(/話してみてください/)
    expect(messageBox()).toBeDisabled()
    await consent()
    await userEvent.type(messageBox(), '転職を迷っています{Enter}')
    expect(api.send).toHaveBeenCalledWith('転職を迷っています', true)
    expect(await screen.findByRole('alert')).toHaveTextContent('Geminiに接続できませんでした。')
    expect(messageBox()).toHaveValue('転職を迷っています')
  })

  it('sends with Enter, clears the input and labels Gemini and legacy mock replies', async () => {
    const legacy: Exchange = { ...exchange(1, '以前の発言'), candidate: null, reply: { provider: 'mock', interpretation: '固定文', question: '' } }
    const api = fakeApi(base({ exchanges: [legacy] }))
    render(<App api={api} />)
    expect(await screen.findByText('以前のモック・固定応答')).toBeInTheDocument()
    await consent()
    await userEvent.type(messageBox(), '一行目{Shift>}{Enter}{/Shift}二行目')
    expect(api.send).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '送信' }))
    expect(api.send).toHaveBeenCalledWith('一行目\n二行目', true)
    expect(await screen.findByText('Geminiの返答（推測を含みます）')).toBeInTheDocument()
    expect(messageBox()).toHaveValue('')
  })

  it('remembers an edited answer only through the explicit action', async () => {
    const api = fakeApi(base({ exchanges: [exchange(1, '家族との時間を大切にしたい')] }))
    render(<App api={api} />)
    await userEvent.click(await screen.findByText('この回答を覚えておく'))
    const box = screen.getByRole('textbox', { name: '覚えておく内容' })
    expect(box).toHaveValue('家族との時間を大切にしたい')
    await userEvent.clear(box)
    await userEvent.type(box, '家族の時間')
    expect(api.approve).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '覚えておく' }))
    expect(api.approve).toHaveBeenCalledWith(1, '家族の時間')
    expect(await screen.findByText('覚えました。これからの対話で参考にします。')).toBeInTheDocument()
    expect(screen.getByText('覚えていること（1件）')).toBeInTheDocument()
    expect(screen.queryByText('この回答を覚えておく')).toBeNull()
    expect(screen.getByText(/保存した回答です/)).toBeInTheDocument()
    expect(screen.getByText('覚えた')).toHaveClass('stamp', 'is-new')
  })

  it('does not press the stamp again for answers already remembered on load', async () => {
    render(<App api={fakeApi(base({ exchanges: [exchange(1, '前に覚えた回答', 'approved')] }))} />)
    expect(await screen.findByText('覚えた')).not.toHaveClass('is-new')
  })

  it('can decline remembering and shows server validation errors', async () => {
    const api = fakeApi(base({ exchanges: [exchange(1, '仮の考え')] }), {
      approve: vi.fn(() => Promise.reject(new ApiError('考えを入力してください'))),
    })
    render(<App api={api} />)
    await userEvent.click(await screen.findByText('この回答を覚えておく'))
    await userEvent.click(screen.getByRole('button', { name: '覚えておく' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('考えを入力してください')
    await userEvent.click(screen.getByRole('button', { name: '今回は覚えない' }))
    expect(api.reject).toHaveBeenCalledWith(1)
    expect(await screen.findByText('会話だけを残し、記憶には追加しませんでした。')).toBeInTheDocument()
    expect(screen.queryByText('この回答を覚えておく')).toBeNull()
  })

  it('forgets a memory and clears the conversation only after separate confirmations', async () => {
    const api = fakeApi(base({ exchanges: [exchange(1, '会話')], memories: [{ id: 7, thought: '残す回答', occurred: '2026-10-25T10:00' }] }))
    render(<App api={api} />)
    await screen.findByText('残す回答')
    const forget = screen.getByRole('button', { name: '忘れる' })
    expect(forget).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: 'この内容を忘れてよい' }))
    await userEvent.click(forget)
    expect(api.forget).toHaveBeenCalledWith(7)
    expect(await screen.findByText('この内容を記憶から外しました。')).toBeInTheDocument()

    const clear = screen.getByRole('button', { name: '会話履歴を削除' })
    expect(clear).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: '会話履歴を削除してよい' }))
    await userEvent.click(clear)
    expect(api.clear).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('会話履歴を削除しました。覚えた回答は残っています。')).toBeInTheDocument()
    expect(screen.getByText(/話してみてください/)).toBeInTheDocument()
  })

  it('resets consent from the connection panel', async () => {
    render(<App api={fakeApi(base())} />)
    await screen.findByText(/話してみてください/)
    await consent()
    expect(messageBox()).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '送信の確認をやり直す' }))
    expect(messageBox()).toBeDisabled()
  })

  it('shows a safe message when the server cannot be reached', async () => {
    const api = fakeApi(base(), { state: vi.fn(() => Promise.reject(new ApiError('保存データにアクセスできません。'))) })
    render(<App api={api} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('保存データにアクセスできません。')
    expect(screen.getByRole('button', { name: 'もう一度読み込む' })).toBeInTheDocument()
  })
})

describe('tone analysis', () => {
  it('sends tone only when selected and resets the selection with consent', async () => {
    const api = fakeApi(base({ toneConfigured: true }))
    render(<App api={api} />)
    const toggle = await screen.findByRole('checkbox', { name: '送信する文章のトーンもGeminiへ渡す' })
    expect(toggle).not.toBeChecked()
    await consent()
    await userEvent.click(toggle)
    await userEvent.type(messageBox(), 'いまの相談{Enter}')
    await waitFor(() => expect(api.send).toHaveBeenCalledWith('いまの相談', true, true))
    await userEvent.click(screen.getByRole('button', { name: '送信の確認をやり直す' }))
    expect(toggle).not.toBeChecked()
    expect(api.tone).not.toHaveBeenCalled()
  })

  it('is disabled until configured and never runs automatically', async () => {
    const api = fakeApi(base({ exchanges: [exchange(1, '発言')] }))
    render(<App api={api} />)
    await userEvent.click(await screen.findByText('文章のトーン（任意）'))
    expect(screen.getByRole('button', { name: '文章のトーンを分析' })).toBeDisabled()
    expect(screen.getByText('分析モデルは未設定です。READMEの「文章のトーン分析」の手順で有効化できます。')).toBeInTheDocument()
    expect(api.tone).not.toHaveBeenCalled()
  })

  it('shows a result or error for that utterance and drops it when the conversation is cleared', async () => {
    const tone = vi.fn().mockResolvedValueOnce({ label: '中立' }).mockRejectedValueOnce(new ApiError('この発言のトーンを推定できませんでした。'))
    const api = fakeApi(base({ toneConfigured: true, exchanges: [exchange(1, '発言')] }), { tone })
    render(<App api={api} />)
    await userEvent.click(await screen.findByText('文章のトーン（任意）'))
    await userEvent.click(screen.getByRole('button', { name: '文章のトーンを分析' }))
    expect(tone).toHaveBeenCalledWith(1)
    expect(await screen.findByText('文章のトーンの推定：中立')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '文章のトーンを分析' }))
    expect(await screen.findByText('この発言のトーンを推定できませんでした。')).toBeInTheDocument()
    expect(screen.queryByText('文章のトーンの推定：中立')).toBeNull()

    // After clearing, a new exchange can reuse ID 1; the old result must not reattach to it.
    await userEvent.click(screen.getByRole('checkbox', { name: '会話履歴を削除してよい' }))
    await userEvent.click(screen.getByRole('button', { name: '会話履歴を削除' }))
    await consent()
    await userEvent.type(messageBox(), '新しい発言{Enter}')
    await screen.findByText('返答1')
    expect(screen.queryByText('この発言のトーンを推定できませんでした。')).toBeNull()
  })
})

describe('voice input', () => {
  const wav = new Blob(['wav'], { type: 'audio/wav' })
  const recorder = (blobs: Blob[]): Recorder =>
    vi.fn(async () => {
      const blob = blobs.shift()!
      return { stop: async () => blob, cancel: vi.fn() }
    })

  const record = async () => {
    await userEvent.click(screen.getByRole('button', { name: /^(録音する|録音し直す)$/ }))
    await userEvent.click(await screen.findByRole('button', { name: /録音を止める/ }))
  }

  it('keeps text input available when the model is not configured', async () => {
    const api = fakeApi(base())
    render(<App api={api} recorder={recorder([wav])} />)
    await userEvent.click(await screen.findByText('音声で入力（任意）'))
    expect(screen.getByRole('button', { name: '録音する' })).toBeDisabled()
    expect(screen.getByText(/音声モデルは未設定です/)).toBeInTheDocument()
    await consent()
    expect(messageBox()).toBeEnabled()
  })

  it('requires review and consent, and sends only the edited text once', async () => {
    const api = fakeApi(base({ voiceConfigured: true }))
    render(<App api={api} recorder={recorder([wav])} />)
    await userEvent.click(await screen.findByText('音声で入力（任意）'))
    await record()
    expect(api.transcribe).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '文字起こし' }))
    expect(api.transcribe).toHaveBeenCalledWith(wav)
    const draft = await screen.findByRole('textbox', { name: '送信する文章（確認・編集）' })
    await waitFor(() => expect(draft).toHaveValue('認識した文章'))
    expect(api.send).not.toHaveBeenCalled()
    const sendVoice = screen.getByRole('button', { name: 'この文章を送信' })
    expect(sendVoice).toBeDisabled()
    expect(screen.getByText('送信にはGeminiの接続設定と、会話の送信確認が必要です。')).toBeInTheDocument()

    await consent()
    await userEvent.clear(draft)
    await userEvent.type(draft, '  直した文章  ')
    await userEvent.click(sendVoice)
    expect(api.send).toHaveBeenCalledTimes(1)
    expect(api.send).toHaveBeenCalledWith('直した文章', true)
    await waitFor(() => expect(screen.queryByRole('textbox', { name: '送信する文章（確認・編集）' })).toBeNull())
  })

  it('a new recording or discard drops the previous draft', async () => {
    const api = fakeApi(base({ voiceConfigured: true }))
    render(<App api={api} recorder={recorder([wav, wav])} />)
    await userEvent.click(await screen.findByText('音声で入力（任意）'))
    await record()
    await userEvent.click(screen.getByRole('button', { name: '文字起こし' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: '送信する文章（確認・編集）' })).toHaveValue('認識した文章'))
    await record()
    expect(screen.getByRole('textbox', { name: '送信する文章（確認・編集）' })).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: '録音と下書きを破棄' }))
    expect(screen.queryByRole('textbox', { name: '送信する文章（確認・編集）' })).toBeNull()
  })

  it('keeps the draft when sending fails and clears it when the conversation is deleted', async () => {
    const api = fakeApi(base({ voiceConfigured: true }), { send: vi.fn(() => Promise.reject(new ApiError('通信に失敗しました。'))) })
    render(<App api={api} recorder={recorder([wav])} />)
    await userEvent.click(await screen.findByText('音声で入力（任意）'))
    await consent()
    await record()
    await userEvent.click(screen.getByRole('button', { name: '文字起こし' }))
    const draft = await screen.findByRole('textbox', { name: '送信する文章（確認・編集）' })
    await waitFor(() => expect(draft).toHaveValue('認識した文章'))
    await userEvent.click(screen.getByRole('button', { name: 'この文章を送信' }))
    expect(await screen.findByText('通信に失敗しました。')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '送信する文章（確認・編集）' })).toHaveValue('認識した文章')

    await userEvent.click(screen.getByRole('checkbox', { name: '会話履歴を削除してよい' }))
    await userEvent.click(screen.getByRole('button', { name: '会話履歴を削除' }))
    await screen.findByText('会話履歴を削除しました。覚えた回答は残っています。')
    expect(screen.queryByRole('textbox', { name: '送信する文章（確認・編集）' })).toBeNull()
  })

  it('shows transcription failures without creating a conversation', async () => {
    const api = fakeApi(base({ voiceConfigured: true }), {
      transcribe: vi.fn(() => Promise.reject(new ApiError('文字起こしに失敗しました。短く録音し直すか、手入力してください。'))),
    })
    render(<App api={api} recorder={recorder([wav])} />)
    await userEvent.click(await screen.findByText('音声で入力（任意）'))
    await record()
    await userEvent.click(screen.getByRole('button', { name: '文字起こし' }))
    const alert = await screen.findByText(/文字起こしに失敗しました/)
    expect(within(alert.closest('details')!).getByText(/文字起こしに失敗しました/)).toBeInTheDocument()
    expect(api.send).not.toHaveBeenCalled()
  })
})
