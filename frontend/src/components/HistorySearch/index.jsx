import { useState } from 'react'

export default function HistorySearch() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState([])
  const [searched, setSearched] = useState(false)
  const [loading, setLoading] = useState(false)

  async function search(e) {
    e.preventDefault()
    const keyword = q.trim()
    if (!keyword) return
    setLoading(true)
    setSearched(false)
    try {
      const res = await fetch(`/api/history/search?q=${encodeURIComponent(keyword)}`)
      setResults(res.ok ? await res.json() : [])
    } catch {
      setResults([])
    } finally {
      setLoading(false)
      setSearched(true)
    }
  }

  return (
    <div className="max-w-2xl mx-auto w-full px-4 py-8 flex flex-col gap-6">
      <form onSubmit={search} className="flex gap-2">
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="키워드로 히스토리 검색"
          className="flex-1 border border-slate-200 bg-white rounded-xl px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-slate-400"
        />
        <button
          type="submit"
          disabled={loading || !q.trim()}
          className="bg-slate-900 text-white text-sm px-5 py-2.5 rounded-xl disabled:opacity-40 hover:bg-slate-700 transition-colors"
        >
          {loading ? '검색 중...' : '검색'}
        </button>
      </form>

      {searched && results.length === 0 && (
        <p className="text-slate-400 text-sm text-center py-8">검색 결과가 없습니다.</p>
      )}

      <div className="flex flex-col gap-3">
        {results.map(r => (
          <div key={r.id} className="bg-white rounded-xl border border-slate-200 px-5 py-4 flex flex-col gap-2">
            <p className="text-sm font-medium text-slate-800">{r.question}</p>
            <p className="text-sm text-slate-600 leading-relaxed line-clamp-3">{r.answer}</p>
            <div className="flex items-center gap-3 pt-1">
              {r.confidence != null && (
                <span className="text-xs text-slate-400">신뢰도 {r.confidence}/5</span>
              )}
              {r.source_law_ids && r.source_law_ids.length > 0 && (
                <span className="text-xs text-slate-400">조문 {r.source_law_ids.length}개</span>
              )}
              <span className="text-xs text-slate-400 ml-auto">
                {new Date(r.created_at).toLocaleDateString('ko-KR')}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
