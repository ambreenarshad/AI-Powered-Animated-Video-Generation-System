import { useEffect, useRef } from 'react'

interface Props {
  logs: string[]
  title?: string
}

function classifyLine(msg: string): string {
  if (msg.includes('✅') || msg.startsWith('[Phase') && msg.includes('✅')) return 'log-green'
  if (msg.includes('❌')) return 'log-red'
  if (
    msg.startsWith('[MCP') ||
    msg.startsWith('[Script') ||
    msg.startsWith('[Voice') ||
    msg.startsWith('[Phase') ||
    msg.startsWith('[HITL') ||
    msg.startsWith('[Edit') ||
    msg.startsWith('[State')
  ) return 'log-gold'
  if (msg.includes('parallel') || msg.includes('branch')) return 'log-blue'
  if (msg.startsWith('  →') || msg.startsWith('  ✅') || msg.startsWith('  ⚠')) return 'log-dim'
  return 'log-normal'
}

export default function LogViewer({ logs, title = 'LIVE LOG' }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="text-xs font-bold text-noir-gold tracking-wider mb-2">{title}</div>
      <div className="flex-1 bg-noir-bg2 rounded border border-noir-border overflow-y-auto p-3 min-h-0">
        {logs.length === 0 ? (
          <span className="text-xs text-noir-muted">No output yet…</span>
        ) : (
          logs.map((line, i) => (
            <div key={i} className={`text-xs leading-5 whitespace-pre-wrap break-all ${classifyLine(line)}`}>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
