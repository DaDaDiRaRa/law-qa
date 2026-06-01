import { useState } from 'react'

const BUILDING_USES = [
  '단독주택',
  '공동주택',
  '제1종 근린생활시설',
  '제2종 근린생활시설',
  '업무시설',
  '판매시설',
  '교육연구시설',
  '의료시설',
  '숙박시설',
  '공장',
  '창고시설',
  '자동차관련시설',
]

export default function ComplianceView() {
  const [form, setForm] = useState({ address: '', building_use: '', total_floor_area: '', floors: '' })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  function setField(key, value) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch('/api/compliance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address: form.address.trim(),
          building_use: form.building_use,
          total_floor_area: form.total_floor_area ? Number(form.total_floor_area) : null,
          floors: form.floors ? Number(form.floors) : null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? '오류가 발생했습니다.')
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto w-full px-4 py-6 flex flex-col gap-6">
      <h2 className="text-base font-semibold text-slate-800">법규 종합 검토</h2>

      <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-500">대지 주소</label>
          <input
            value={form.address}
            onChange={e => setField('address', e.target.value)}
            placeholder="예: 서울 강남구 삼성동 1"
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300"
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">건물 용도</label>
            <select
              value={form.building_use}
              onChange={e => setField('building_use', e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300 bg-white"
            >
              <option value="">선택</option>
              {BUILDING_USES.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">연면적 (㎡)</label>
            <input
              type="number"
              value={form.total_floor_area}
              onChange={e => setField('total_floor_area', e.target.value)}
              placeholder="예: 5000"
              min="0"
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-500">층수</label>
            <input
              type="number"
              value={form.floors}
              onChange={e => setField('floors', e.target.value)}
              placeholder="예: 10"
              min="1"
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="bg-slate-900 text-white rounded-xl px-4 py-2.5 text-sm font-medium disabled:opacity-40 hover:bg-slate-700 transition-colors"
        >
          {loading ? '검토 중...' : '종합 검토'}
        </button>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-4">
          {(result.address || result.zone_use) && (
            <div className="text-xs text-blue-700 bg-blue-50 rounded-lg px-3 py-2">
              📍 {result.address}{result.zone_use && ` — ${result.zone_use}`}
            </div>
          )}

          {result.items.map(item => (
            <ComplianceCard key={item.topic} item={item} />
          ))}

          <p className="text-xs text-slate-400 text-center">{result.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

function ComplianceCard({ item }) {
  const unavailable = item.answer.includes('확인 불가')
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 bg-slate-50">
        <span className="text-sm font-semibold text-slate-700">{item.topic}</span>
        {unavailable && (
          <span className="ml-2 text-xs text-slate-400">확인 불가</span>
        )}
      </div>
      <div className="px-4 py-3 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
        {item.answer}
      </div>
      {item.source_laws?.length > 0 && (
        <div className="px-4 pb-3 flex flex-col gap-1.5">
          {item.source_laws.map(law => (
            <SourceLaw key={law.id} law={law} />
          ))}
        </div>
      )}
    </div>
  )
}

function SourceLaw({ law }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-slate-200 rounded-lg text-xs overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        <span className="text-slate-600 font-medium leading-snug">
          {law.title} / {law.article_no}
        </span>
        <span className="text-slate-400 shrink-0">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 py-2.5 text-slate-500 leading-relaxed whitespace-pre-wrap border-t border-slate-100 bg-white">
          {law.content}
        </div>
      )}
    </div>
  )
}
