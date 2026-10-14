import { useEffect, useRef } from 'react'

function fmtTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export default function TimelineScrubber({
  total,
  scrubIndex,
  playing,
  onChange,
  onPlayToggle,
  disabled,
  oldestAt,
  newestAt,
}) {
  const isLive = scrubIndex === null
  const current = isLive ? total - 1 : scrubIndex
  const sliderRef = useRef(null)

  useEffect(() => {
    if (playing && sliderRef.current) {
      sliderRef.current.focus({ preventScroll: true })
    }
  }, [playing])

  if (disabled || total <= 1) return null

  const handleSlider = (e) => {
    const v = Number(e.target.value)
    if (v >= total - 1) onChange(null)
    else onChange(v)
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/80 bg-white px-3 py-2 shadow-[0_4px_18px_rgba(27,65,110,0.05)] dark:border-slate-700 dark:bg-slate-900">
      <button
        type="button"
        onClick={onPlayToggle}
        title={playing ? 'Pause replay' : 'Play replay'}
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-xs font-semibold transition ${
          playing
            ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200'
            : 'border-slate-200 bg-white text-slate-700 hover:border-sky-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
        }`}
      >
        {playing ? '⏸' : '▶'}
      </button>

      <span className="shrink-0 font-mono text-[11px] text-slate-500 dark:text-slate-400">
        {fmtTime(oldestAt)}
      </span>

      <input
        ref={sliderRef}
        type="range"
        min={0}
        max={total - 1}
        value={current}
        onChange={handleSlider}
        className="h-1 min-w-[180px] flex-1 cursor-pointer appearance-none rounded-full bg-slate-200 accent-sky-600 dark:bg-slate-700"
      />

      <span className="shrink-0 font-mono text-[11px] text-slate-500 dark:text-slate-400">
        {fmtTime(newestAt)}
      </span>

      <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-700 dark:bg-slate-800 dark:text-slate-200">
        {current + 1} / {total}
      </span>

      {isLive ? (
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-200">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Live
        </span>
      ) : (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-semibold text-sky-600 transition hover:border-sky-300 dark:border-slate-700 dark:bg-slate-800 dark:text-sky-400"
        >
          Jump to live
        </button>
      )}
    </div>
  )
}