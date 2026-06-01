import { useEffect, useRef, useState } from 'react'

export default function ChatWindow({ project, onBack }) {
  const [question, setQuestion] = useState('')
  const [image, setImage] = useState(null)  // { file, base64 }
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)
  const fileRef = useRef(null)

  // 이전 히스토리 로드
  useEffect(() => {
    fetch(`/api/projects/${project.id}/history`)
      .then(r => r.json())
      .then(rows => {
        const msgs = rows.flatMap(r => [
          { role: 'user', text: r.question, id: `q-${r.id}` },
          {
            role: 'assistant',
            text: r.answer,
            sourceLaws: [],
            confidence: r.confidence,
            id: `a-${r.id}`,
          },
        ]).reverse()
        setMessages(msgs)
      })
      .catch(() => {})
  }, [project.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  function handleFile(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => setImage({ file, base64: ev.target.result.split(',')[1] })
    reader.readAsDataURL(file)
  }

  async function send(e) {
    e.preventDefault()
    const q = question.trim()
    if (!q || loading) return

    setMessages(prev => [...prev, { role: 'user', text: q, image: image?.file?.name, id: Date.now() }])
    setQuestion('')
    setImage(null)
    if (fileRef.current) fileRef.current.value = ''
    setLoading(true)
    setError(null)

    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: project.id,
          question: q,
          image_base64: image?.base64 ?? null,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail ?? '오류가 발생했습니다.')
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          text: data.answer,
          sourceLaws: data.source_laws ?? [],
          confidence: data.confidence,
          id: data.history_id,
        },
      ])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] max-w-3xl mx-auto w-full">
      {/* 서브 헤더 */}
      <div className="px-4 py-3 border-b border-slate-200 bg-white flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-slate-500 hover:text-slate-800 text-sm transition-colors"
        >
          ← 목록
        </button>
        <span className="text-slate-800 font-medium truncate">{project.name}</span>
        {project.description && (
          <span className="text-sm text-slate-400 truncate hidden sm:block">{project.description}</span>
        )}
      </div>

      {/* 메시지 영역 */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {messages.length === 0 && !loading && (
          <p className="text-slate-400 text-sm text-center mt-16">
            건축법규에 대해 질문해 보세요.
          </p>
        )}
        {messages.map(msg => (
          <Message key={msg.id} msg={msg} />
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 rounded-2xl px-4 py-3 text-slate-400 text-sm">
              답변 생성 중...
            </div>
          </div>
        )}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-red-600 text-sm">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 입력 영역 */}
      <form onSubmit={send} className="border-t border-slate-200 bg-white px-4 py-3 flex flex-col gap-2">
        {image && (
          <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-lg px-3 py-2">
            <span>📎 {image.file.name}</span>
            <button type="button" onClick={() => { setImage(null); fileRef.current.value = '' }} className="ml-auto text-slate-400 hover:text-red-500">✕</button>
          </div>
        )}
        <div className="flex gap-2">
          <textarea
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e) } }}
            placeholder="건축법규 질문을 입력하세요 (Shift+Enter 줄바꿈)"
            rows={2}
            className="flex-1 border border-slate-200 rounded-xl px-3 py-2 text-sm resize-none outline-none focus:ring-2 focus:ring-slate-400"
          />
          <div className="flex flex-col gap-1">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="border border-slate-200 rounded-xl px-3 py-2 text-slate-500 hover:bg-slate-50 text-sm transition-colors"
              title="이미지 첨부"
            >
              📎
            </button>
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="bg-slate-900 text-white rounded-xl px-3 py-2 text-sm disabled:opacity-40 hover:bg-slate-700 transition-colors"
            >
              전송
            </button>
          </div>
        </div>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
        <p className="text-xs text-slate-400 text-center">
          참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수.
        </p>
      </form>
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

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] flex flex-col gap-2 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap leading-relaxed ${
            isUser
              ? 'bg-slate-900 text-white'
              : 'bg-white border border-slate-200 text-slate-800'
          }`}
        >
          {msg.image && (
            <p className="text-xs opacity-60 mb-1">📎 {msg.image}</p>
          )}
          {msg.text}
        </div>

        {msg.sourceLaws && msg.sourceLaws.length > 0 && (
          <div className="flex flex-col gap-1.5 w-full">
            {msg.sourceLaws.map(law => (
              <SourceLaw key={law.id} law={law} />
            ))}
          </div>
        )}

        {msg.confidence != null && (
          <p className="text-xs text-slate-400">신뢰도 {msg.confidence}/5</p>
        )}
      </div>
    </div>
  )
}
