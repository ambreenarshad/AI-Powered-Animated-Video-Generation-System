import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import LogViewer from './LogViewer'

interface Version {
  version_id: number
  label: string
  timestamp: string
  asset_paths: string[]
  diff_summary: string
  source?: 'edit' | 'pipeline'
}

interface Phase4Status {
  status: 'idle' | 'running' | 'completed' | 'error'
  last_intent?: string
  error?: string
}

interface Props {
  logs: string[]
  onClearLogs: () => void
}

const INTENT_COLORS: Record<string, string> = {
  audio:       'text-noir-blue',
  video_frame: 'text-noir-gold',
  video:       'text-noir-gold',
  script:      'text-noir-green',
}

export default function Phase4Panel({ logs, onClearLogs }: Props) {
  const [editText, setEditText] = useState('')
  const [status, setStatus] = useState<Phase4Status>({ status: 'idle' })
  const [versions, setVersions] = useState<Version[]>([])
  const [error, setError] = useState<string | null>(null)
  const [revertMsg, setRevertMsg] = useState<string | null>(null)

  const loadHistory = useCallback(async () => {
    try {
      const { versions: v } = await api.getHistory() as { versions: Version[] }
      setVersions(v)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const handleSubmitEdit = async () => {
    if (!editText.trim()) return
    try {
      setError(null)
      onClearLogs()
      await api.submitEdit(editText.trim())
      setStatus({ status: 'running' })

      // Poll until done
      const poll = setInterval(async () => {
        try {
          const s = await api.getPhase4Status() as Phase4Status
          setStatus(s)
          if (s.status !== 'running') {
            clearInterval(poll)
            if (s.status === 'completed') {
              setEditText('')
              loadHistory()
            }
          }
        } catch {}
      }, 1000)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const handleRevert = async (versionId: number) => {
    try {
      setRevertMsg(null)
      await api.revertVersion(versionId)
      setRevertMsg(`✅ Reverted to version ${versionId}`)
      loadHistory()
    } catch (e) {
      setRevertMsg(`❌ Revert failed: ${(e as Error).message}`)
    }
  }

  const isRunning = status.status === 'running'
  const intentColor = status.last_intent ? (INTENT_COLORS[status.last_intent] ?? 'text-noir-muted') : 'text-noir-muted'

  return (
    <div className="flex h-full p-5 gap-5 overflow-hidden">
      {/* ── Left column ── */}
      <div className="flex flex-col gap-4 w-[50%] overflow-y-auto pr-1">
        {/* Edit input */}
        <div className="bg-noir-bg2 border border-noir-border rounded p-4">
          <div className="text-xs font-bold text-noir-gold tracking-wider mb-1">EDIT COMMAND</div>
          <p className="text-xs text-noir-muted mb-3">
            Describe an edit in plain text — the system classifies the intent and applies it.
            Examples: "Make the voice deeper", "Change scene 2 to daytime", "Rewrite the ending".
          </p>
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            disabled={isRunning}
            rows={4}
            placeholder="e.g. Make the dialogue in scene 1 more tense…"
            className="w-full bg-noir-bg3 text-noir-white font-mono text-sm p-3 rounded resize-none outline-none border border-transparent focus:border-noir-gold disabled:opacity-60"
          />
        </div>

        <button
          onClick={handleSubmitEdit}
          disabled={isRunning || !editText.trim()}
          className="w-full py-3 bg-noir-gold text-noir-bg font-bold text-sm tracking-widest rounded hover:bg-noir-gold2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? '⏳  APPLYING EDIT…' : '▶  APPLY EDIT'}
        </button>

        {/* Intent + status display */}
        {(status.last_intent || status.status !== 'idle') && (
          <div className={`bg-noir-bg2 border rounded px-4 py-3 ${status.status === 'error' ? 'border-noir-red' : 'border-noir-border'}`}>
            {status.last_intent && (
              <div className="mb-1">
                <span className="text-xs font-bold text-noir-gold tracking-wider">CLASSIFIED AS&nbsp;&nbsp;</span>
                <span className={`text-xs font-bold uppercase tracking-wider ${intentColor}`}>
                  {status.last_intent.replace(/_/g, ' ')}
                </span>
              </div>
            )}
            {status.status === 'error' && status.error && (
              <div className="text-xs text-noir-red mt-1">❌ {status.error}</div>
            )}
            {status.status === 'completed' && (
              <div className="text-xs text-noir-green mt-1">
                ✅ Edit applied — check outputs/ for updated files
              </div>
            )}
          </div>
        )}

        {/* Error from API call (not executor) */}
        {error && (
          <div className="bg-noir-bg2 border border-noir-red rounded p-3 text-xs text-noir-red">
            ❌ {error}
          </div>
        )}

        {/* Revert message */}
        {revertMsg && (
          <div className={`bg-noir-bg2 border rounded p-3 text-xs ${revertMsg.startsWith('✅') ? 'border-noir-green text-noir-green' : 'border-noir-red text-noir-red'}`}>
            {revertMsg}
          </div>
        )}

        {/* Version history */}
        <div className="bg-noir-bg2 border border-noir-border rounded p-4">
          <div className="flex justify-between items-center mb-3">
            <span className="text-xs font-bold text-noir-gold tracking-wider">VERSION HISTORY</span>
            <button
              onClick={loadHistory}
              className="text-xs text-noir-muted hover:text-noir-gold transition-colors"
            >
              ↺ refresh
            </button>
          </div>

          {versions.length === 0 ? (
            <p className="text-xs text-noir-muted">No snapshots yet — run the pipeline to create one.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {versions.map((v) => (
                <div
                  key={`${v.source}-${v.version_id}`}
                  className="bg-noir-bg3 rounded p-3 border border-noir-border"
                >
                  <div className="flex justify-between items-start mb-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-noir-gold text-xs font-bold">v{v.version_id}</span>
                      {v.source === 'edit' && (
                        <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: '#c9a84c22', color: '#c9a84c' }}>edit</span>
                      )}
                      {v.source === 'pipeline' && (
                        <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: '#4caf8422', color: '#4caf84' }}>pipeline</span>
                      )}
                      <span className="text-noir-white text-xs">{v.label}</span>
                    </div>
                    <button
                      onClick={() => handleRevert(v.version_id)}
                      className="text-xs text-noir-muted hover:text-noir-red border border-noir-border rounded px-2 py-0.5 transition-colors ml-2 flex-shrink-0"
                    >
                      ↩ revert
                    </button>
                  </div>
                  <div className="text-xs text-noir-muted mb-1">{v.timestamp}</div>
                  {v.diff_summary && (
                    <div className="text-xs text-noir-muted italic leading-4">{v.diff_summary}</div>
                  )}
                  {v.asset_paths?.length > 0 && (
                    <div className="mt-1 text-xs text-noir-muted">
                      {v.asset_paths.length} asset{v.asset_paths.length !== 1 ? 's' : ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Right column ── */}
      <div className="flex flex-col gap-4 flex-1 min-h-0">
        {/* Status */}
        <div className="bg-noir-bg2 border border-noir-border rounded px-4 py-2">
          <span className="text-xs font-bold text-noir-gold tracking-wider">STATUS&nbsp;&nbsp;</span>
          <span className={`text-xs ${status.status === 'error' ? 'text-noir-red' : status.status === 'completed' ? 'text-noir-green' : 'text-noir-muted'}`}>
            {status.status === 'idle'      ? 'Ready'
            : status.status === 'running'  ? '⏳ Applying edit…'
            : status.status === 'completed'? '✅ Edit applied'
            : `❌ ${status.error ?? 'Error'}`}
          </span>
        </div>
        <LogViewer logs={logs} title="EDIT LOG" />
      </div>
    </div>
  )
}
