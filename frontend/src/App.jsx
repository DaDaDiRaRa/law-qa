import { useState, useEffect } from 'react'
import ProjectList from './components/ProjectList'
import ChatWindow from './components/ChatWindow'
import HistorySearch from './components/HistorySearch'
import ComplianceView from './components/ComplianceView'

const DEFAULT_PROJECT_NAME = '기본 프로젝트'

export default function App() {
  const [view, setView] = useState('chat')
  const [selectedProject, setSelectedProject] = useState(null)
  const [initError, setInitError] = useState(null)

  useEffect(() => {
    async function init() {
      try {
        const res = await fetch('/api/projects')
        if (!res.ok) throw new Error()
        const list = await res.json()
        let proj = list.find(p => p.name === DEFAULT_PROJECT_NAME)
        if (!proj) {
          const r2 = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: DEFAULT_PROJECT_NAME }),
          })
          if (!r2.ok) throw new Error()
          proj = await r2.json()
        }
        setSelectedProject(proj)
      } catch {
        setInitError('서버 연결 실패. 백엔드가 실행 중인지 확인하세요.')
      }
    }
    init()
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-4">
        <h1
          className="text-lg font-semibold text-slate-800 cursor-pointer select-none"
          onClick={() => setView('chat')}
        >
          건축법규 QA
        </h1>
        <nav className="flex gap-1 ml-auto">
          <NavBtn active={view === 'chat'} onClick={() => setView('chat')}>
            질의
          </NavBtn>
          <NavBtn active={view === 'projects'} onClick={() => setView('projects')}>
            프로젝트 관리
          </NavBtn>
          <NavBtn active={view === 'search'} onClick={() => setView('search')}>
            히스토리 검색
          </NavBtn>
          <NavBtn active={view === 'compliance'} onClick={() => setView('compliance')}>
            종합 검토
          </NavBtn>
        </nav>
      </header>

      <main className="flex-1 flex flex-col">
        {view === 'chat' && (
          selectedProject
            ? <ChatWindow
                project={selectedProject}
                onProjectChange={setSelectedProject}
              />
            : <div className="flex-1 flex items-center justify-center text-slate-400 text-sm py-24">
                {initError ?? '초기화 중...'}
              </div>
        )}
        {view === 'projects' && (
          <ProjectList onSelect={p => { setSelectedProject(p); setView('chat') }} />
        )}
        {view === 'search' && <HistorySearch />}
        {view === 'compliance' && <ComplianceView />}
      </main>
    </div>
  )
}

function NavBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
        active
          ? 'bg-slate-900 text-white'
          : 'text-slate-600 hover:bg-slate-100'
      }`}
    >
      {children}
    </button>
  )
}
