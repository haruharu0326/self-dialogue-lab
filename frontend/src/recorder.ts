/** Browser recording converted to the 16 kHz mono 16-bit WAV that voice.validate_audio accepts. */

export const MAX_SECONDS = 60
const RATE = 16000

export type Recording = { stop: () => Promise<Blob>; cancel: () => void }
export type Recorder = (onLimit: () => void) => Promise<Recording>

export class RecorderError extends Error {}

function encodeWav(samples: Float32Array): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const text = (offset: number, value: string) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, RATE, true)
  view.setUint32(28, RATE * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((sample, i) => {
    const clipped = Math.max(-1, Math.min(1, sample))
    view.setInt16(44 + i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true)
  })
  return new Blob([buffer], { type: 'audio/wav' })
}

async function toWav(recorded: Blob): Promise<Blob> {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await recorded.arrayBuffer())
    const seconds = Math.min(decoded.duration, MAX_SECONDS)
    const offline = new OfflineAudioContext(1, Math.max(1, Math.floor(seconds * RATE)), RATE)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    return encodeWav((await offline.startRendering()).getChannelData(0))
  } finally {
    void context.close()
  }
}

export const browserRecorder: Recorder = async (onLimit) => {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    throw new RecorderError('このブラウザでは録音できません。http://127.0.0.1:8501 で開くか、手入力を使ってください。')
  }
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } })
  } catch {
    throw new RecorderError('マイクを使えませんでした。ブラウザのマイク許可を確認してください。')
  }
  const chunks: Blob[] = []
  const media = new MediaRecorder(stream)
  media.ondataavailable = (event) => event.data.size && chunks.push(event.data)
  const limit = window.setTimeout(onLimit, MAX_SECONDS * 1000)
  const release = () => {
    window.clearTimeout(limit)
    stream.getTracks().forEach((track) => track.stop())
  }
  media.start()
  return {
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        media.onstop = () => {
          release()
          toWav(new Blob(chunks, { type: media.mimeType }))
            .then(resolve)
            .catch(() => reject(new RecorderError('録音を読み込めません。マイクで録音し直してください。')))
        }
        media.stop()
      }),
    cancel: () => {
      media.onstop = release
      if (media.state !== 'inactive') media.stop()
      else release()
    },
  }
}
