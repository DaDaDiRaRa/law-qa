import { useState } from 'react'
import ProjectList from './components/ProjectList'
import ChatWindow from './components/ChatWindow'
import HistorySearch from './components/HistorySearch'

export default function App() {
  const [view, setView] = useState('projects')
  const [selectedProject, setSelectedProject] = useState(null)

  function openChat(project) {
    setSelectedProject(project)
    setView('chat')
  }

  function goBack() {
    setView('projects')
    setSelectedProject(null)
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* 헤더 */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-4">
        <h1
          className="text-lg font-semibold text-slate-800 cursor-pointer select-none"
          onClick={goBack}
        >
          건축법규 QA
        </h1>
        <nav className="flex gap-1 ml-auto">
          <NavBtn active={view === 'projects'} onClick={() => { setView('projects'); setSelectedProject(null) }}>
            프로젝트
          </NavBtn>
          <NavBtn active={view === 'search'} onClick={() => setView('search')}>
            히스토리 검색
          </NavBtn>
        </nav>
      </header>

      {/* 본문 */}
      <main className="flex-1 flex flex-col">
        {view === 'projects' && <ProjectList onSelect={openChat} />}
        {view === 'chat' && selectedProject && (
          <ChatWindow project={selectedProject} onBack={goBack} />
        )}
        {view === 'search' && <HistorySearch />}
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
