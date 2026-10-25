import type { AppState } from './types'

/** Messages come from the server's safe, user-facing errors only. */
export class ApiError extends Error {}

const OFFLINE = 'アプリのサーバーに接続できません。起動状態を確認して、もう一度お試しください。'
const FAILED = '処理できませんでした。時間をおいて、もう一度お試しください。'

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof Blob) {
    init.headers = { 'Content-Type': 'audio/wav' }
    init.body = body
  } else if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError(OFFLINE)
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(typeof data?.detail === 'string' ? data.detail : FAILED)
  return data as T
}

export const api = {
  state: () => call<AppState>('GET', '/api/state'),
  send: (text: string, consent: boolean) => call<AppState>('POST', '/api/messages', { text, consent }),
  approve: (id: number, thought: string) => call<AppState>('POST', `/api/candidates/${id}/approve`, { thought }),
  reject: (id: number) => call<AppState>('POST', `/api/candidates/${id}/reject`),
  forget: (id: number) => call<AppState>('DELETE', `/api/memories/${id}`),
  clear: () => call<AppState>('DELETE', '/api/conversations'),
  tone: (id: number) => call<{ label: string }>('POST', `/api/exchanges/${id}/tone`),
  transcribe: (wav: Blob) => call<{ text: string }>('POST', '/api/voice/transcribe', wav),
}

export type Api = typeof api

export const messageOf = (error: unknown) => (error instanceof ApiError ? error.message : FAILED)
