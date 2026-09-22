import { useState } from 'react'

const initialForm = { name: '', manufacturer: '', ingredient: '', strength: '', dosage_form: '' }

async function searchMedicines(payload) {
  const response = await fetch('/api/medicines/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error((await response.text()) || 'Search failed')
  return response.json()
}

function Ingredients({ items = [] }) {
  if (!items.length) return <span className="text-slate-400 dark:text-slate-500">Not recorded</span>
  return items.map((item, index) => (
    <span key={`${item.name}-${index}`}>
      {index > 0 && ', '}{item.name}{item.strength_text ? ` ${item.strength_text}` : item.strength ? ` ${item.strength} ${item.unit || ''}` : ''}
    </span>
  ))
}

function ProductSummary({ match, selected, onSelect }) {
  const product = match.product
  return (
    <button
      type="button"
      onClick={() => onSelect(match)}
      className={`w-full border-b border-slate-200 p-4 text-left transition last:border-b-0 dark:border-slate-700 ${selected ? 'bg-sky-50 dark:bg-sky-950/40' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="truncate font-semibold text-slate-900 dark:text-slate-100">{product.name}</h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{product.manufacturer || 'Manufacturer not recorded'}</p>
          <p className="mt-2 line-clamp-2 text-sm text-slate-500 dark:text-slate-400"><Ingredients items={product.ingredients} /></p>
        </div>
        <span className="shrink-0 rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700 dark:bg-sky-950 dark:text-sky-300">{match.relevance}%</span>
      </div>
    </button>
  )
}

function DetailPanel({ selected }) {
  if (!selected) {
    return <div className="flex min-h-30 items-start justify-center p-8 pt-10 text-center"><div><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-50 text-xl text-sky-600 dark:bg-sky-950">+</div><h2 className="mt-4 font-semibold text-slate-900 dark:text-slate-100">Select a possible match</h2><p className="mt-2 max-w-xs text-sm leading-6 text-slate-500 dark:text-slate-400">Regulatory status, composition, and source documents will appear here.</p></div></div>
  }

  const product = selected.product
  return (
    <div className="p-4 sm:p-5">
      <div className="border-b border-slate-200 pb-4 dark:border-slate-700">
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-sky-700">Selected result</p>
        <h2 className="mt-1.5 text-xl font-bold leading-tight text-slate-900 dark:text-slate-100">{product.name}</h2>
        <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-300">{product.manufacturer || 'Manufacturer not recorded'}</p>
        <span className="mt-2 inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">{selected.relevance}% match</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-5 gap-y-3 border-b border-slate-200 py-4 text-sm dark:border-slate-700">
        <div><dt className="text-slate-500 dark:text-slate-400">Brand</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{product.brand_name || 'Not recorded'}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">Strength</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{product.strength || 'Not recorded'}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">Dosage form</dt><dd className="mt-0.5 font-medium text-slate-800 dark:text-slate-200">{product.dosage_form || 'Not recorded'}</dd></div>
        <div><dt className="text-slate-500 dark:text-slate-400">Composition</dt><dd className="mt-0.5 font-medium leading-5 text-slate-800 dark:text-slate-200"><Ingredients items={product.ingredients} /></dd></div>
      </dl>
      <div className="border-b border-slate-200 py-4 dark:border-slate-700">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">Regulatory information</h3>
        {selected.regulatory_events.length ? selected.regulatory_events.map((event, index) => <div key={`${event.event_type}-${index}`} className="mt-2 rounded-lg bg-slate-50 p-2.5 text-sm dark:bg-slate-800"><p className="font-semibold text-slate-800 dark:text-slate-200">{event.event_type}{event.status ? ` · ${event.status}` : ''}</p>{event.reason && <p className="mt-0.5 leading-5 text-slate-600 dark:text-slate-300">{event.reason}</p>}{event.source && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{event.source.title || event.source.pdf_filename || `Document ${event.source.document_id}`}</p>}</div>) : <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No regulatory events recorded.</p>}
      </div>
      <div className="pt-4"><h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">Source references</h3>{selected.source_references.length ? selected.source_references.map((source) => <div key={`${source.document_id}-${source.source_record_id}`} className="mt-2 text-sm leading-5 text-slate-600 dark:text-slate-300">{source.title || source.pdf_filename || `Document ${source.document_id}`}</div>) : <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No source references recorded.</p>}</div>
    </div>
  )
}

export default function MedicineSearch() {
  const [form, setForm] = useState(initialForm)
  const [matches, setMatches] = useState([])
  const [selected, setSelected] = useState(null)
  const [state, setState] = useState('idle')
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setState('loading')
    setError('')
    setSelected(null)
    try {
      const data = await searchMedicines(form)
      setMatches(data.matches || [])
      setState('complete')
    } catch (requestError) {
      setError(requestError.message)
      setState('error')
    }
  }

  const update = (name, value) => setForm((current) => ({ ...current, [name]: value }))
  const fields = [['name', 'Brand or medicine name'], ['manufacturer', 'Manufacturer'], ['ingredient', 'Active ingredient'], ['strength', 'Strength'], ['dosage_form', 'Dosage form']]

  return (
    <main className="min-h-[calc(100vh-66px)] px-4 py-8 text-slate-800 dark:text-slate-100 sm:px-6">
      <div className="mx-auto max-w-[1500px]">
        <header className="mb-7"><p className="text-[11px] font-bold uppercase tracking-[0.18em] text-sky-700">Identification workspace</p><h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">Find regulatory information</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">Enter details read from a medicine package. The search tolerates partial names and imperfect OCR.</p></header>
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_520px]">
          <div>
            <form onSubmit={submit} className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1fr_1.6fr]">
                {fields.map(([name, label], index) => <label key={name} className={index === 0 ? 'text-sm font-semibold text-slate-700 dark:text-slate-200 lg:col-span-2' : 'text-sm font-semibold text-slate-700 dark:text-slate-200'}>{label}<input value={form[name]} onChange={(event) => update(name, event.target.value)} placeholder={index === 0 ? 'PARACETAMOL 500MG' : 'Optional'} className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 font-normal text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-sky-500 focus:ring-2 focus:ring-sky-100 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:placeholder:text-slate-500" /></label>)}
                <button type="submit" disabled={state === 'loading'} className="w-full self-end rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-bold text-white shadow-sm transition hover:bg-sky-500 disabled:cursor-wait disabled:opacity-60">{state === 'loading' ? 'Searching...' : 'Search records'}</button>
              </div>
            </form>
            {error && <div className="mb-5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>}
            <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
              <div className="border-b border-slate-200 p-5 dark:border-slate-700"><div className="flex items-center justify-between gap-4"><h2 className="font-bold text-slate-900 dark:text-slate-100">Possible matches</h2>{matches.length > 0 && <span className="text-sm text-slate-500 dark:text-slate-400">{matches.length} found</span>}</div><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Choose the closest package identity to inspect its record.</p></div>
              {state === 'idle' && <div className="px-6 py-16 text-center text-sm text-slate-500 dark:text-slate-400">Search by the name or composition printed on the package.</div>}
              {state === 'complete' && matches.length === 0 && <div className="px-6 py-16 text-center text-sm text-slate-500 dark:text-slate-400">No matching regulatory records were found.</div>}
              {state === 'loading' && <div className="px-6 py-16 text-center text-sm text-slate-500 dark:text-slate-400">Searching the regulatory database...</div>}
              {matches.map((match) => <ProductSummary key={match.id} match={match} selected={selected?.id === match.id} onSelect={setSelected} />)}
            </section>
          </div>
          <aside className="sticky top-5 rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900"><DetailPanel selected={selected} /></aside>
        </div>
      </div>
    </main>
  )
}
