export type Candidate = { id: number; status: 'pending' | 'approved' | 'rejected'; thought: string }

export type Exchange = {
  id: number
  message: string
  candidate: Candidate | null
  reply: { provider: 'gemini' | 'mock'; interpretation: string; question: string }
  refs: { thought: string }[]
}

export type Memory = { id: number; thought: string; occurred: string }

export type AppState = {
  configured: boolean
  voiceConfigured: boolean
  toneConfigured: boolean
  exchanges: Exchange[]
  memories: Memory[]
}
