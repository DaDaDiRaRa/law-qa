import { useEffect, useState } from 'react'

export default function ProjectList({ onSelect }) {
  const [projects, setProjects] = useState([])
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [creating, setCreating] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  async function load() {
    try {
      const res = await fetch('/api/projects')
      if (!res.ok) throw new Error('서버 오류')
      setProjects(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function create(e) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: desc.trim() || null }),
      })
      if (!res.ok) throw new Error('생성 실패')
      setName('')
      setDesc('')
      await load()
    } finally {
      setCreating(false)
    }
  }

  async function remove(id, e) {
    e.stopPropagation()
    if (!confirm('프로젝트를 삭제하면 히스토리도 함께 삭제됩니다. 계속하시겠습니까?')) return
    await fetch(`/api/projects/${id}`, { method: 'DELETE' })
    await load()
  }

  return (
    <div className="max-w-2xl mx-auto w-full px-4 py-8 flex flex-col gap-6">
      {/* 생성 폼 */}
      <form onSubmit={create} className="bg-white rounded-xl border border-slate-200 p-5 flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide">새 프로젝트</h2>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="프로젝트명"
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-400"
        />
        <input
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="설명 (선택)"
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-400"
        />
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="self-end bg-slate-900 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-40 hover:bg-slate-700 transition-colors"
        >
          {creating ? '생성 중...' : '생성'}
        </button>
      </form>

      {/* 목록 */}
      <div className="flex flex-col gap-2">
        {loading && <p className="text-slate-400 text-sm text-center py-8">불러오는 중...</p>}
        {error && <p className="text-red-500 text-sm text-center py-4">{error}</p>}
        {!loading && projects.length === 0 && (
          <p className="text-slate-400 text-sm text-center py-8">프로젝트가 없습니다.</p>
        )}
        {projects.map(p => (
          <div
            key={p.id}
            onClick={() => onSelect(p)}
            className="bg-white rounded-xl border border-slate-200 px-5 py-4 flex items-start justify-between gap-3 cursor-pointer hover:border-slate-400 transition-colors group"
          >
            <div className="min-w-0">
              <p className="font-medium text-slate-800 truncate">{p.name}</p>
              {p.description && (
                <p className="text-sm text-slate-500 mt-0.5 truncate">{p.description}</p>
              )}
              <p className="text-xs text-slate-400 mt-1">{new Date(p.updated_at).toLocaleDateString('ko-KR')}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs text-slate-400 group-hover:text-slate-600">질의하기 →</span>
              <button
                onClick={e => remove(p.id, e)}
                className="text-slate-300 hover:text-red-500 text-xs transition-colors"
                title="삭제"
              >
                삭제
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
