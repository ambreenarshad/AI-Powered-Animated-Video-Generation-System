import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'
import LogViewer from './LogViewer'
import StageProgress from './StageProgress'

const STAGES = [
  'Manifest Loader',
  'Image Gen (wan2.5-t2i-preview)',
  'Video Gen (wan2.7-i2v-2026-04-25)',
  'A/V Sync',
  'Scene Merge',
  'Compositor',
]

type StageState = 'idle' | 'running' | 'done' | 'error'

interface Phase3Status {
  status: 'idle' | 'running' | 'completed' | 'error'
  stages: Record<string, StageState>
  error?: string
}

interface ConfigResponse {
  dashscope_api_key_set: boolean
  dashscope_api_key_hint: string
  groq_api_key_set: boolean
}

interface Props {
  logs: string[]
  onClearLogs: () => void
}

export default function Phase3Panel({ logs, onClearLogs }: Props) {
  const [apiKey, setApiKey] = useState('')
  const [keyFromEnv, setKeyFromEnv] = useState(false)
  const [keyHint, setKeyHint] = useState('')
  const [status, setStatus] = useState<Phase3Status>({
    status: 'idle',
    stages: Object.fromEntries(STAGES.map((s) => [s, 'idle' as StageState])),
  })
  const [error, setError] = useState<string | null>(null)
  const [showKey, setShowKey] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isRunning = status.status === 'running'

  // On mount: fetch config to check if DASHSCOPE_API_KEY is in .env
  useEffect(() => {
    api.getConfig().then((cfg) => {
      const c = cfg as ConfigResponse
      if (c.dashscope_api_key_set) {
        setKeyFromEnv(true)
        setKeyHint(c.dashscope_api_key_hint)
      }
    }).catch(() => {})
  }, [])

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPoll = () => {
    stopPoll()
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.getPhase3Status() as Phase3Status
        setStatus(s)
        if (s.status !== 'running') stopPoll()
      } catch {}
    }, 1500)
  }

  useEffect(() => () => stopPoll(), [])

  const handleRun = async () => {
    // Send the typed key (or empty string — backend will fall back to .env)
    if (!apiKey.trim() && !keyFromEnv) {
      setError('DashScope API key is required — add it to .env or paste it here')
      return
    }
    try {
      setError(null)
      onClearLogs()
      await api.runPhase3(apiKey.trim())   // empty string → backend uses .env
      setStatus({
        status: 'running',
        stages: Object.fromEntries(STAGES.map((s) => [s, 'idle' as StageState])),
      })
      startPoll()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const doneCount = Object.values(status.stages).filter((v) => v === 'done').length
  const progressPct = STAGES.length > 0 ? Math.round((doneCount / STAGES.length) * 100) : 0

  const statusLabel = {
    idle: 'Ready',
    running: `⏳ Running… (${doneCount}/${STAGES.length} stages)`,
    completed: '✅ Phase 3 Complete — video ready',
    error: '❌ Error — see log',
  }[status.status]

  const canRun = !isRunning && (!!apiKey.trim() || keyFromEnv)

  return (
    <div className="flex h-full p-5 gap-5 overflow-hidden">
      {/* ── Left column ── */}
      <div className="flex flex-col gap-4 w-[40%] overflow-y-auto pr-1">
        {/* API key input */}
        <div className="bg-noir-bg2 border border-noir-border rounded p-4">
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs font-bold text-noir-gold tracking-wider">DASHSCOPE API KEY</span>
            {keyFromEnv && (
              <span className="text-xs text-noir-green font-bold">✓ loaded from .env</span>
            )}
          </div>
          <p className="text-xs text-noir-muted mb-3">
            Used for image generation (wan2.5-t2i) and video synthesis (wan2.7-i2v).
            {keyFromEnv && ' Leave blank to use the key from your .env file.'}
          </p>
          <div className="flex gap-2">
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={keyFromEnv ? `${keyHint}  (from .env — override here)` : 'sk-…'}
              disabled={isRunning}
              className="flex-1 bg-noir-bg3 text-noir-white font-mono text-sm p-2 rounded outline-none border border-transparent focus:border-noir-gold disabled:opacity-60"
            />
            <button
              onClick={() => setShowKey((v) => !v)}
              className="px-3 text-xs text-noir-muted hover:text-noir-gold border border-noir-border rounded transition-colors"
            >
              {showKey ? 'hide' : 'show'}
            </button>
          </div>
        </div>

        {/* Input paths (informational) */}
        <div className="bg-noir-bg2 border border-noir-border rounded p-4">
          <div className="text-xs font-bold text-noir-gold tracking-wider mb-2">INPUT PATHS</div>
          <p className="text-xs text-noir-muted mb-2">Reads from these output files:</p>
          {[
            'outputs/scene_manifest.json',
            'outputs/timing_manifest.json',
            'outputs/character_db.json',
            'outputs/audio/',
          ].map((p) => (
            <div key={p} className="flex items-center gap-2 py-1">
              <span className="text-noir-muted text-xs">▸</span>
              <span className="text-xs font-mono text-noir-muted">{p}</span>
            </div>
          ))}
        </div>

        {/* Run button */}
        <button
          onClick={handleRun}
          disabled={!canRun}
          className="w-full py-3 bg-noir-gold text-noir-bg font-bold text-sm tracking-widest rounded hover:bg-noir-gold2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? '⏳  GENERATING…' : '▶  RUN PHASE 3 PIPELINE'}
        </button>

        {/* Error */}
        {error && (
          <div className="bg-noir-bg2 border border-noir-red rounded p-3 text-xs text-noir-red">
            ❌ {error}
          </div>
        )}

        {/* Download video */}
        {status.status === 'completed' && (
          <a
            href={api.videoUrl()}
            download="final_output.mp4"
            className="block w-full py-3 bg-noir-green text-noir-bg font-bold text-sm tracking-widest rounded hover:opacity-90 transition-opacity text-center"
          >
            ⬇&nbsp;&nbsp;DOWNLOAD FINAL VIDEO
          </a>
        )}
      </div>

      {/* ── Right column ── */}
      <div className="flex flex-col gap-4 flex-1 min-h-0">
        {/* Status + progress bar */}
        <div className="bg-noir-bg2 border border-noir-border rounded px-4 py-3">
          <div className="flex justify-between items-center mb-2">
            <span className={`text-xs font-bold ${status.status === 'error' ? 'text-noir-red' : status.status === 'completed' ? 'text-noir-green' : 'text-noir-gold'}`}>
              {statusLabel}
            </span>
            {isRunning && (
              <span className="text-xs text-noir-muted">{progressPct}%</span>
            )}
          </div>
          {(isRunning || status.status === 'completed') && (
            <div className="w-full bg-noir-bg3 rounded-full h-1.5">
              <div
                className="h-1.5 rounded-full transition-all duration-500"
                style={{
                  width: `${progressPct}%`,
                  backgroundColor: status.status === 'completed' ? '#4caf84' : '#c9a84c',
                }}
              />
            </div>
          )}
        </div>

        <StageProgress stages={STAGES} stageStatus={status.stages} title="VIDEO PIPELINE STAGES" />

        <LogViewer logs={logs} title="LIVE LOG" />
      </div>
    </div>
  )
}
