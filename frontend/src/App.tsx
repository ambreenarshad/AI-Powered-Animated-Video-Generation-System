import { useState } from 'react'
import Phase1Panel from './components/Phase1Panel'
import Phase2Panel from './components/Phase2Panel'
import Phase3Panel from './components/Phase3Panel'
import Phase4Panel from './components/Phase4Panel'
import { useWebSocket } from './hooks/useWebSocket'

const TABS = [
  { id: 1, label: 'PHASE 1  ·  Story Generation' },
  { id: 2, label: 'PHASE 2  ·  Audio Synthesis' },
  { id: 3, label: 'PHASE 3  ·  Video Creation' },
  { id: 4, label: 'PHASE 4  ·  Edit & Undo' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState(1)
  const { logs, connected, clearLogs } = useWebSocket(
    `ws://${location.host}/ws/logs`
  )

  return (
    <div className="flex flex-col h-screen bg-noir-bg text-noir-white font-mono overflow-hidden">
      {/* Header */}
      <header className="flex items-baseline gap-4 px-8 py-4 border-b border-noir-border flex-shrink-0">
        <h1 className="text-xl font-bold text-noir-gold font-serif tracking-wide">
          ◈&nbsp;&nbsp;PROJECT MONTAGE
        </h1>
        <span className="text-noir-muted text-xs italic">
          autonomous story · audio · per-character video generation
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: connected ? '#4caf84' : '#7a7060' }}
          />
          <span className="text-xs text-noir-muted">
            {connected ? 'live' : 'disconnected'}
          </span>
        </div>
      </header>

      {/* Tab bar */}
      <nav className="flex border-b bg-noir-bg2 flex-shrink-0" style={{ borderColor: '#2e2e2e' }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-6 py-3 text-xs font-bold tracking-widest transition-colors cursor-pointer ${
              activeTab === tab.id
                ? 'bg-noir-bg text-noir-gold border-b-2 border-noir-gold'
                : 'text-noir-muted hover:text-noir-gold bg-noir-bg2'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      <main className="flex-1 overflow-hidden">
        {activeTab === 1 && <Phase1Panel logs={logs} onClearLogs={clearLogs} />}
        {activeTab === 2 && <Phase2Panel logs={logs} onClearLogs={clearLogs} />}
        {activeTab === 3 && <Phase3Panel logs={logs} onClearLogs={clearLogs} />}
        {activeTab === 4 && <Phase4Panel logs={logs} onClearLogs={clearLogs} />}
      </main>
    </div>
  )
}
