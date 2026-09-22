import { useEffect, useState } from 'react'

const statusStyles = {
  downloaded: 'bg-emerald-100 text-emerald-700',
  seeded: 'bg-emerald-100 text-emerald-700',
  discovered: 'bg-sky-100 text-sky-700',
  failed: 'bg-rose-100 text-rose-700',
}

const sourceTabs = [
  { key: 'all', label: 'All sources' },
  { key: 'cdsco_alerts', label: 'CDSCO Alerts' },
  { key: 'cdsco_fdc', label: 'CDSCO FDC' },
  { key: 'cdsco_banned_drugs', label: 'Banned Drugs' },
  { key: 'ipc_pvpi', label: 'IPC / PvPI' },
  { key: 'cdsco_nsq', label: 'NSQ / Spurious' },
]

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || 'Request failed')
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  return response.text()
}

function fmtLocalTime(dateString) {
  if (!dateString) return '—'
  const date = new Date(dateString)
  if (Number.isNaN(date.getTime())) return dateString

  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fmtBytes(value) {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(2)} MB`
}

function formatScheduleLabel(cron) {
  const hour = Number(cron.hour)
  const minute = Number(cron.minute)
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return 'Custom cron schedule'
  const suffix = hour >= 12 ? 'PM' : 'AM'
  const displayHour = hour % 12 || 12
  return `Every day at ${displayHour}:${String(minute).padStart(2, '0')} ${suffix}`
}

function editorHourValue(hour) {
  const numericHour = Number(hour)
  if (!Number.isInteger(numericHour) || numericHour < 0 || numericHour > 23) return hour
  return String(numericHour % 12 || 12)
}

function editorPeriod(hour) {
  const numericHour = Number(hour)
  return Number.isInteger(numericHour) && numericHour >= 12 ? 'PM' : 'AM'
}

function cronHourFromEditor(value, period) {
  const numericHour = Number(value)
  if (!Number.isInteger(numericHour) || numericHour < 1 || numericHour > 12) return value
  if (period === 'AM') return String(numericHour === 12 ? 0 : numericHour)
  return String(numericHour === 12 ? 12 : numericHour + 12)
}

function normalizeScheduler(data = {}) {
  return {
    cron: {
      minute: String(data.minute ?? '0'),
      hour: String(data.hour ?? '0'),
      day_of_month: String(data.day_of_month ?? '*'),
      month: String(data.month ?? '*'),
      day_of_week: String(data.day_of_week ?? '?'),
      year: String(data.year ?? '*'),
    },
    enabled: !!data.enabled,
  }
}

export default function Homepage() {
  const [documents, setDocuments] = useState([])
  const [scheduler, setScheduler] = useState({
    cron: { minute: '0', hour: '2', day_of_month: '*', month: '*', day_of_week: '?', year: '*' },
    enabled: true,
  })
  const [scraperStatus, setScraperStatus] = useState({ status: 'idle', running: false })
  const [activeSource, setActiveSource] = useState('all')
  const [documentQuery, setDocumentQuery] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [deletingDocumentId, setDeletingDocumentId] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [isEditingSchedule, setIsEditingSchedule] = useState(false)
  const [scheduleError, setScheduleError] = useState('')
  const [schedulePeriod, setSchedulePeriod] = useState('AM')
  const [scheduleDraft, setScheduleDraft] = useState(null)

  const loadScheduler = async () => {
    const data = await api('/api/scheduler')
    const nextScheduler = normalizeScheduler(data)
    setScheduler(nextScheduler)
    setSchedulePeriod(editorPeriod(nextScheduler.cron.hour))
  }

  const loadDocuments = async () => {
    const data = await api('/api/documents')
    setDocuments(data.documents || [])
  }

  const refreshDocuments = async () => {
    setIsRefreshing(true)
    try {
      await loadDocuments()
    } finally {
      setIsRefreshing(false)
    }
  }

  const loadScraperStatus = async () => {
    const data = await api('/api/admin/scraper/status')
    setScraperStatus(data)
  }

  const loadAll = async () => {
    setIsLoading(true)
    try {
      await Promise.all([loadScheduler(), loadDocuments(), loadScraperStatus()])
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const saveSchedule = async () => {
    setScheduleError('')
    const payload = { ...scheduleDraft, enabled: scheduler.enabled }
    try {
      const updated = await api('/api/scheduler', {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
      const nextScheduler = normalizeScheduler(updated)
      setScheduler(nextScheduler)
      setSchedulePeriod(editorPeriod(nextScheduler.cron.hour))
      setIsEditingSchedule(false)
      setScheduleDraft(null)
    } catch (error) {
      setScheduleError(error.message)
    }
  }

  const toggleScheduler = async () => {
    const nextEnabled = !scheduler.enabled
    const updated = await api('/api/scheduler', {
      method: 'PUT',
      body: JSON.stringify({
        ...scheduler.cron,
        enabled: nextEnabled,
      }),
    })
    const nextScheduler = normalizeScheduler(updated)
    setScheduler(nextScheduler)
  }

  const triggerNow = async () => {
    await api('/api/scheduler/run-now', { method: 'POST' })
    await loadAll()
  }

  const openScheduleEditor = () => {
    setScheduleDraft({ ...scheduler.cron })
    setSchedulePeriod(editorPeriod(scheduler.cron.hour))
    setScheduleError('')
    setIsEditingSchedule(true)
  }

  const closeScheduleEditor = () => {
    setScheduleDraft(null)
    setScheduleError('')
    setIsEditingSchedule(false)
  }

  const deleteDocument = async (document) => {
    const confirmed = window.confirm(`Delete "${document.title}" from the database and S3 storage? This cannot be undone.`)
    if (!confirmed) return

    setDeletingDocumentId(document.document_id)
    setDeleteError('')
    try {
      await api(`/api/documents/${document.document_id}`, { method: 'DELETE' })
      setDocuments((current) => current.filter((item) => item.document_id !== document.document_id))
    } catch (error) {
      setDeleteError(error.message)
    } finally {
      setDeletingDocumentId(null)
    }
  }

  const visibleDocuments = activeSource === 'all'
    ? documents
    : documents.filter((document) => document.source === activeSource)

  const searchedDocuments = documentQuery.trim()
    ? visibleDocuments.filter((document) => `${document.title} ${document.document_id}`.toLowerCase().includes(documentQuery.toLowerCase()))
    : visibleDocuments

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f3f7fc] text-slate-500">
        Loading…
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#f3f7fc] px-5 py-7 text-slate-800">
      <div className="mx-auto max-w-[1350px]">
        <header className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-blue-500">
              Medicine scanner
            </p>
            <h1 className="mt-1 text-[23px] font-bold tracking-tight text-[#0d2443]">Admin Panel</h1>
            <p className="mt-1 text-xs text-blue-500">Monitor document ingestion, scraper activity and regulatory data collection.</p>
          </div>
          <span className={`mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold ${scraperStatus.running ? 'border-amber-200 bg-amber-50 text-amber-700' : scheduler.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {scraperStatus.running ? 'Scraper running' : scheduler.enabled ? 'Scheduler active' : 'Scheduler inactive'}
          </span>
        </header>

        <section className="mb-4 overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-[0_4px_18px_rgba(27,65,110,0.06)]">
          <div className="flex flex-col gap-5 p-4 sm:p-5 xl:flex-row xl:items-center">
            <div className="flex min-w-[290px] items-center gap-4 border-b border-slate-100 pb-4 xl:border-b-0 xl:border-r xl:pb-0 xl:pr-7">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-2xl text-blue-500">◫</div>
              <div>
                <div className="text-[11px] font-medium text-blue-500">Automation</div>
                <div className="mt-1 text-sm font-bold text-[#17375e]">Scraper schedule</div>
                <p className="mt-1 max-w-[190px] text-[10px] leading-4 text-slate-500">Automatically fetch new documents on a recurring schedule.</p>
              </div>
            </div>

            <div className="grid flex-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="border-r border-slate-100 pr-4">
                <div className="flex items-center gap-2 text-[10px] text-blue-500"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />Status</div>
                <div className="mt-2 text-xs font-bold text-[#17375e]">{scraperStatus.running ? 'Running' : scheduler.enabled ? 'Active' : 'Disabled'}</div>
              </div>
              <div className="border-r border-slate-100 pr-4">
                <div className="text-[10px] text-blue-500">▣ &nbsp;Schedule</div>
                <div className="mt-2 text-xs font-bold text-[#17375e]">{formatScheduleLabel(scheduler.cron)}</div>
              </div>
              <div className="border-r border-slate-100 pr-4">
                <div className="text-[10px] text-blue-500">⊕ &nbsp;Timezone</div>
                <div className="mt-2 text-xs font-bold text-[#17375e]">Asia/Calcutta</div>
              </div>
              <div>
                <div className="text-[10px] text-blue-500">◷ &nbsp;Next run</div>
                <div className="mt-2 text-xs font-bold text-[#17375e]">Today · {formatScheduleLabel(scheduler.cron).replace('Every day at ', '')}</div>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-3 border-t border-slate-100 bg-blue-50/50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#28527e]"><span className="font-mono text-blue-500">&lt;/&gt;</span> Advanced scheduling</div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-[11px] text-slate-500">Cron expression: cron({scheduler.cron.minute} {scheduler.cron.hour} {scheduler.cron.day_of_month} {scheduler.cron.month} {scheduler.cron.day_of_week} {scheduler.cron.year})</span>
              <button type="button" onClick={() => navigator.clipboard?.writeText(`cron(${scheduler.cron.minute} ${scheduler.cron.hour} ${scheduler.cron.day_of_month} ${scheduler.cron.month} ${scheduler.cron.day_of_week} ${scheduler.cron.year})`)} className="text-xs font-semibold text-blue-600 hover:text-blue-800">▣ Copy</button>
              <button type="button" onClick={isEditingSchedule ? closeScheduleEditor : openScheduleEditor} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500">{isEditingSchedule ? 'Close editor' : 'Edit schedule'}</button>
              <button type="button" onClick={triggerNow} className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-[#28527e] shadow-sm hover:border-blue-300">▷ Run now</button>
              <button type="button" onClick={toggleScheduler} className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-[#28527e] shadow-sm hover:border-blue-300">Ⅱ {scheduler.enabled ? 'Disable' : 'Enable'}</button>
            </div>
          </div>
          {isEditingSchedule && scheduleDraft && <div className="border-t border-slate-100 bg-white p-4 sm:p-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {[
                ['hour', 'Hours', '1-12'],
                ['minute', 'Minutes', '0-59'],
                ['day_of_month', 'Day of month', '1-31 or *'],
                ['month', 'Month', '1-12 or *'],
                ['day_of_week', 'Day of week', '1-7 or ?'],
                ['year', 'Year', '1970-2199 or *'],
              ].map(([name, label, placeholder]) => (
                <label key={name} htmlFor={`cron-${name}`} className="text-[10px] font-semibold text-blue-500">
                  {label}
                  <div className="mt-1 flex gap-1">
                    <input id={`cron-${name}`} value={name === 'hour' ? editorHourValue(scheduleDraft[name]) : scheduleDraft[name]} onFocus={name === 'hour' ? (event) => event.target.select() : undefined} onChange={(event) => setScheduleDraft((current) => ({ ...current, [name]: name === 'hour' ? cronHourFromEditor(event.target.value, schedulePeriod) : event.target.value }))} placeholder={placeholder} inputMode={name === 'hour' ? 'numeric' : undefined} maxLength={name === 'hour' ? 2 : undefined} className="w-full min-w-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-2 text-center text-sm font-semibold text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                    {name === 'hour' && <select aria-label="AM or PM" value={schedulePeriod} onChange={(event) => { setSchedulePeriod(event.target.value); setScheduleDraft((current) => ({ ...current, hour: cronHourFromEditor(editorHourValue(current.hour), event.target.value) })) }} className="rounded-md border border-slate-200 bg-slate-50 px-1 text-xs font-semibold text-slate-700 outline-none focus:border-blue-500"><option>AM</option><option>PM</option></select>}
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <code className="text-xs text-slate-500">cron({scheduleDraft.minute} {scheduleDraft.hour} {scheduleDraft.day_of_month} {scheduleDraft.month} {scheduleDraft.day_of_week} {scheduleDraft.year})</code>
              <div className="flex items-center gap-2">
                {scheduleError && <span className="text-xs text-rose-600">{scheduleError}</span>}
                <button type="button" onClick={closeScheduleEditor} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600">Cancel</button>
                <button type="button" onClick={saveSchedule} className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white">Save schedule</button>
              </div>
            </div>
          </div>}
        </section>

        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['▤', 'Documents', documents.length, 'Total records collected', 'bg-blue-50 text-blue-500'],
            ['↓', 'Downloaded', documents.filter((document) => document.status === 'downloaded' || document.status === 'seeded').length, 'Successfully downloaded', 'bg-emerald-50 text-emerald-500'],
            ['!', 'Failed', documents.filter((document) => document.status === 'failed').length, 'Failed to process', 'bg-rose-50 text-rose-500'],
            ['◷', 'Last refresh', fmtLocalTime(new Date().toISOString()).split(' ')[1], new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }), 'bg-blue-50 text-blue-500'],
          ].map(([icon, label, value, caption, iconStyle]) => (
            <div key={label} className="flex items-center gap-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_4px_18px_rgba(27,65,110,0.05)]">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg font-bold ${iconStyle}`}>{icon}</div>
              <div className="min-w-0"><div className="text-[10px] font-medium text-blue-500">{label}</div><div className="mt-1 text-lg font-bold leading-none text-[#17375e]">{value}</div><div className="mt-1 truncate text-[10px] text-blue-400">{caption}</div></div>
            </div>
          ))}
        </div>

        <section className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_4px_18px_rgba(27,65,110,0.05)] sm:p-5">
          {deleteError && <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">{deleteError}</div>}
          <div className="mb-4 flex flex-col gap-4 border-b border-slate-200 pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-base font-bold text-[#17375e]">Documents</div>
              <div className="mt-1 text-xs text-blue-400">Latest records collected by the scraper.</div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-400 shadow-sm"><span>⌕</span><input value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Search documents..." className="w-32 border-0 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400 sm:w-40" /></label>
              <button type="button" onClick={refreshDocuments} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-[#28527e] shadow-sm hover:border-blue-300">↻ {isRefreshing ? 'Refreshing' : 'Refresh'}</button>
            </div>
          </div>
          <div className="mb-4 flex max-w-full gap-1 overflow-x-auto rounded-lg bg-[#f3f7fc] p-1">
              {sourceTabs.map((tab) => {
                const count = tab.key === 'all'
                  ? documents.length
                  : documents.filter((document) => document.source === tab.key).length
                const selected = activeSource === tab.key

                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveSource(tab.key)}
                    className={`flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition ${selected ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
                    aria-pressed={selected}
                  >
                    {tab.label}
                    <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${selected ? 'bg-sky-100 text-sky-700' : 'bg-white/70 text-slate-500'}`}>{count}</span>
                  </button>
                )
              })}
            </div>

          {searchedDocuments.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 py-12 text-center text-slate-400">
              No documents found for this source.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-slate-600">
                  <tr>
                    <th className="px-3 py-3 font-medium">#</th>
                    <th className="px-3 py-3 font-medium">Title</th>
                    <th className="px-3 py-3 font-medium">Release</th>
                    <th className="px-3 py-3 font-medium">Status</th>
                    <th className="px-3 py-3 font-medium">Size</th>
                    <th className="px-3 py-3 font-medium">Actions</th>
                  </tr>
                </thead>

                <tbody>
                  {searchedDocuments.map((document, index) => {
                    const pdfUrl = `/api/documents/${document.document_id}/pdf`

                    return (
                      <tr key={document.document_id} className="border-t border-slate-200 align-top">
                        <td className="px-3 py-3 font-mono text-slate-500">{index + 1}</td>
                        <td className="px-3 py-3">
                          <div className="font-medium text-slate-800">{document.title}</div>
                          <div className="mt-1 font-mono text-xs text-slate-500">DOC {document.document_id}</div>
                        </td>
                        <td className="px-3 py-3 text-slate-600">{document.release_date || '—'}</td>
                        <td className="px-3 py-3">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                              statusStyles[document.status] || 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {document.status || 'discovered'}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-slate-600">{fmtBytes(document.file_size_bytes)}</td>
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-3">
                            <a href={pdfUrl} target="_blank" rel="noreferrer" className="font-semibold text-sky-600 hover:text-sky-700">View PDF</a>
                            <button
                              type="button"
                              onClick={() => deleteDocument(document)}
                              disabled={deletingDocumentId === document.document_id}
                              className="font-semibold text-rose-600 hover:text-rose-700 disabled:cursor-wait disabled:opacity-50"
                            >
                              {deletingDocumentId === document.document_id ? 'Deleting...' : 'Delete'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
