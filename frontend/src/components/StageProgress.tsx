type StageState = 'idle' | 'running' | 'done' | 'error'

interface Props {
  title?: string
  stages: string[]
  stageStatus: Record<string, StageState>
}

const DOT: Record<StageState, string> = {
  idle:    '○',
  running: '◉',
  done:    '●',
  error:   '✗',
}

const COLOR: Record<StageState, string> = {
  idle:    'text-noir-muted',
  running: 'text-noir-gold',
  done:    'text-noir-green',
  error:   'text-noir-red',
}

export default function StageProgress({ stages, stageStatus, title = 'PIPELINE PROGRESS' }: Props) {
  return (
    <div className="bg-noir-bg2 border border-noir-border rounded p-4">
      <div className="text-xs font-bold text-noir-gold tracking-wider mb-3">{title}</div>
      <div className="flex flex-col gap-2">
        {stages.map((stage) => {
          const s: StageState = (stageStatus[stage] as StageState) ?? 'idle'
          return (
            <div key={stage} className={`flex items-center gap-2 text-xs ${COLOR[s]}`}>
              <span className="w-4 flex-shrink-0">{DOT[s]}</span>
              <span>{stage}</span>
              {s === 'running' && (
                <span className="ml-1 animate-pulse text-noir-gold">…</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
