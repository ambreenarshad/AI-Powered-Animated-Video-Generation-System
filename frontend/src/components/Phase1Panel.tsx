import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'
import LogViewer from './LogViewer'
import StageProgress from './StageProgress'

const STAGES = ['Scriptwriter', 'Validator', 'HITL Review', 'Character Designer']

const DEFAULT_PROMPT =
  'Write a 3-scene thriller in New York City. ' +
  'Two main characters planning a heist. ' +
  'Include tense dialogues and cinematic visual cues.'

type StageState = 'idle' | 'running' | 'done' | 'error'

interface Phase1Status {
  status: 'idle' | 'running' | 'hitl_pending' | 'completed' | 'error'
  script?: object
  characters?: unknown[]
  error?: string
  stages: Record<string, StageState>
}

interface Props {
  logs: string[]
  onClearLogs: () => void
}

function detectMode(text: string) {
  const s = text.trim()
  if (s.startsWith('{') || s.startsWith('[')) {
    try { JSON.parse(s); return 'manual' } catch {}
  }
  if (/^Scene\s*\d+\s*:/im.test(s)) return 'manual'
  return 'auto'
}

export default function Phase1Panel({ logs, onClearLogs }: Props) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [status, setStatus] = useState<Phase1Status>({
    status: 'idle',
    stages: Object.fromEntries(STAGES.map((s) => [s, 'idle' as StageState])),
  })
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isRunning = status.status === 'running' || status.status === 'hitl_pending'
  const mode = detectMode(prompt)

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startPoll = () => {
    stopPoll()
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.getPhase1Status() as Phase1Status
        setStatus(s)
        if (!['running', 'hitl_pending'].includes(s.status)) stopPoll()
      } catch { /* network blip — keep polling */ }
    }, 1000)
  }

  useEffect(() => () => stopPoll(), [])

  const handleRun = async () => {
    try {
      setError(null)
      onClearLogs()
      await api.runPhase1(prompt)
      setStatus({ status: 'running', stages: Object.fromEntries(STAGES.map((s) => [s, 'idle' as StageState])) })
      startPoll()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleApprove = async () => {
    try {
      await api.submitHITL('approve')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleReject = async () => {
    try {
      await api.submitHITL('reject', feedback)
      setFeedback('')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const statusLabel = {
    idle: 'Ready',
    running: '⏳ Pipeline running…',
    hitl_pending: '⬡ Awaiting human review…',
    completed: '✅ Phase 1 Complete',
    error: '❌ Error — see log',
  }[status.status]

  return (
    <div className="flex h-full p-5 gap-5 overflow-hidden">
      {/* ── Left column ── */}
      <div className="flex flex-col gap-4 w-[55%] overflow-y-auto pr-1">
        {/* Prompt input */}
        <div className="bg-noir-bg2 border border-noir-border rounded p-4">
          <div className="flex justify-between items-center mb-1">
            <span className="text-xs font-bold text-noir-gold tracking-wider">PROMPT / SCRIPT</span>
            <span className={`text-xs font-bold ${mode === 'manual' ? 'text-noir-gold' : 'text-noir-green'}`}>
              {mode === 'manual' ? '⚙  SCRIPT / JSON' : '⚡  AUTO PROMPT'}
            </span>
          </div>
          <p className="text-xs text-noir-muted mb-3">
            Enter a plain prompt or paste a raw screenplay (Scene 1: … Speaker: … [Visual] …).
            Mode is detected automatically.
          </p>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isRunning}
            rows={7}
            className="w-full bg-noir-bg3 text-noir-white font-mono text-sm p-3 rounded resize-none outline-none border border-transparent focus:border-noir-gold disabled:opacity-60"
          />
        </div>

        {/* Run button */}
        <button
          onClick={handleRun}
          disabled={isRunning || !prompt.trim()}
          className="w-full py-3 bg-noir-gold text-noir-bg font-bold text-sm tracking-widest rounded hover:bg-noir-gold2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? '⏳  RUNNING…' : '▶  RUN PIPELINE'}
        </button>

        {/* Error */}
        {error && (
          <div className="bg-noir-bg2 border border-noir-red rounded p-3 text-xs text-noir-red">
            ❌ {error}
          </div>
        )}

        {/* HITL review panel */}
        {status.status === 'hitl_pending' && (
          <div className="bg-noir-bg2 border-2 border-noir-gold rounded p-4">
            <div className="text-xs font-bold text-noir-gold tracking-wider mb-3">
              ⬡&nbsp;&nbsp;HUMAN REVIEW CHECKPOINT
            </div>
            <pre className="bg-noir-bg3 text-noir-cream text-xs p-3 rounded h-44 overflow-auto mb-3 leading-5">
              {JSON.stringify(status.script, null, 2)}
            </pre>
            <label className="text-xs font-bold text-noir-gold block mb-1 tracking-wider">
              FEEDBACK (optional)
            </label>
            <input
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Provide feedback for regeneration…"
              className="w-full bg-noir-bg3 text-noir-white font-mono text-sm p-2 rounded outline-none border border-transparent focus:border-noir-gold mb-3"
            />
            <div className="flex gap-3">
              <button
                onClick={handleApprove}
                className="px-5 py-2 bg-noir-green text-noir-bg font-bold text-xs tracking-wider rounded hover:opacity-90 transition-opacity"
              >
                ✓&nbsp;&nbsp;APPROVE
              </button>
              <button
                onClick={handleReject}
                className="px-5 py-2 bg-noir-red text-noir-white font-bold text-xs tracking-wider rounded hover:opacity-90 transition-opacity"
              >
                ✗&nbsp;&nbsp;REJECT & REGENERATE
              </button>
            </div>
          </div>
        )}

        {/* Output files */}
        {status.status === 'completed' && (
          <div className="bg-noir-bg2 border border-noir-border rounded p-4">
            <div className="text-xs font-bold text-noir-gold tracking-wider mb-2">OUTPUT FILES</div>
            {['outputs/scene_manifest.json', 'outputs/character_db.json'].map((f) => (
              <div key={f} className="flex items-center gap-2 py-1">
                <span className="text-noir-green text-xs">▸</span>
                <span className="text-noir-green text-xs font-mono">{f}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Right column ── */}
      <div className="flex flex-col gap-4 flex-1 min-h-0">
        <StageProgress stages={STAGES} stageStatus={status.stages} />

        {/* Status bar */}
        <div className="bg-noir-bg2 border border-noir-border rounded px-4 py-2">
          <span className="text-xs font-bold text-noir-gold tracking-wider">STATUS&nbsp;&nbsp;</span>
          <span className={`text-xs ${status.status === 'error' ? 'text-noir-red' : status.status === 'completed' ? 'text-noir-green' : 'text-noir-muted'}`}>
            {statusLabel}
          </span>
        </div>

        <LogViewer logs={logs} title="LIVE LOG" />
      </div>
    </div>
  )
}
