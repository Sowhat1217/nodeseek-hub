import { useMemo, useState, type KeyboardEvent, type PointerEvent } from "react"
import { useWidth } from "@/lib/hooks"
import { md } from "@/lib/format"
import { cn } from "@/lib/utils"

export interface LineSeries {
  key: string
  color: string // css var, e.g. var(--series-1)
  /** value = the line; day = optional raw value for that date, drawn as a faint dot */
  points: { date: string; value: number; day?: number | null; n?: number }[]
}

const H = 300
const M = { top: 16, right: 16, bottom: 28, left: 52 }
const LABEL_W = 108 // room on the right for direct labels

function niceTicks(lo: number, hi: number, count = 5) {
  if (lo === hi) hi = lo + 1
  const raw = (hi - lo) / count
  const p = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw
  const start = Math.floor(lo / step) * step
  const ticks = []
  for (let v = start; v <= hi + step * 0.001; v += step) ticks.push(Math.round(v * 1e6) / 1e6)
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

/**
 * Multi-series line chart over a fixed list of dates.
 * Crosshair snaps to the nearest date and lists every series there; legend items isolate a series on hover.
 * ≤4 series also get direct labels at their last point, so identity never rests on colour alone.
 */
export function LineChart({
  dates,
  series,
  format,
  ariaLabel,
  zeroLine = true,
  dayLabel = true,
  note,
}: {
  dates: string[]
  series: LineSeries[]
  format: (v: number) => string
  ariaLabel: string
  zeroLine?: boolean
  dayLabel?: boolean
  /** small line under the date in the tooltip, e.g. what the line means */
  note?: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const direct = series.length <= 4 && width > 560
  const right = M.right + (direct ? LABEL_W : 0)
  const iw = Math.max(0, width - M.left - right)
  const ih = H - M.top - M.bottom

  const { ticks, y, x, byDate } = useMemo(() => {
    const vals = series.flatMap((s) => s.points.flatMap((p) => (p.day != null ? [p.value, p.day] : [p.value])))
    let lo = vals.length ? Math.min(...vals) : 0
    let hi = vals.length ? Math.max(...vals) : 1
    if (zeroLine) lo = Math.min(0, lo)
    const pad = (hi - lo) * 0.08
    const ticks = niceTicks(lo, hi + pad)
    const t0 = ticks[0]
    const t1 = ticks[ticks.length - 1]
    const idx = new Map(dates.map((d, i) => [d, i]))
    const x = (d: string) => (dates.length <= 1 ? iw / 2 : ((idx.get(d) ?? 0) / (dates.length - 1)) * iw)
    const y = (v: number) => ih - ((v - t0) / (t1 - t0 || 1)) * ih
    const byDate = dates.map((d) => series.map((s) => s.points.find((p) => p.date === d) ?? null))
    return { ticks, y, x, byDate }
  }, [series, dates, iw, ih, zeroLine])

  // direct labels: last point of each series, nudged apart vertically
  const labels = useMemo(() => {
    if (!direct) return []
    const ls = series
      .filter((s) => s.points.length)
      .map((s) => ({ key: s.key, color: s.color, y: y(s.points[s.points.length - 1].value) }))
      .sort((a, b) => a.y - b.y)
    for (let i = 1; i < ls.length; i++) if (ls[i].y - ls[i - 1].y < 16) ls[i].y = ls[i - 1].y + 16
    return ls
  }, [series, direct, y])

  const step = dates.length > 1 ? iw / (dates.length - 1) : iw
  const xTickEvery = Math.max(1, Math.ceil(dates.length / Math.max(2, Math.floor(iw / 64))))

  function onMove(e: PointerEvent<SVGRectElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - r.left
    setHoverIdx(Math.max(0, Math.min(dates.length - 1, Math.round(px / (step || 1)))))
  }
  function onKey(e: KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return
    e.preventDefault()
    setHoverIdx((i) => Math.max(0, Math.min(dates.length - 1, (i ?? dates.length - 1) + (e.key === "ArrowLeft" ? -1 : 1))))
  }

  const hi = hoverIdx
  const tipLeft = hi === null ? 0 : M.left + hi * step
  const tipOnLeft = hi !== null && tipLeft > width * 0.62

  return (
    <div>
      {series.length > 1 && (
        <ul className="mb-4 flex flex-wrap gap-x-4 gap-y-1.5" aria-label="图例">
          {series.map((s) => (
            <li key={s.key}>
              <button
                onPointerEnter={() => setFocusKey(s.key)}
                onPointerLeave={() => setFocusKey(null)}
                onFocus={() => setFocusKey(s.key)}
                onBlur={() => setFocusKey(null)}
                className={cn(
                  "flex items-center gap-2 rounded-sm text-[13px] text-muted-foreground transition-opacity focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                  focusKey && focusKey !== s.key && "opacity-40",
                )}
              >
                <span aria-hidden className="h-[3px] w-3.5 rounded-full" style={{ background: s.color }} />
                <span className="text-foreground">{s.key}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div ref={ref} className="relative" style={{ height: H }}>
        {width > 0 && (
          <svg
            width={width}
            height={H}
            role="img"
            aria-label={ariaLabel}
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHoverIdx(null)}
            className="overflow-visible focus-visible:outline-none"
          >
            <g transform={`translate(${M.left},${M.top})`}>
              {ticks.map((t) => (
                <g key={t} transform={`translate(0,${y(t)})`}>
                  <line x2={iw} className={t === 0 ? "stroke-border" : "stroke-grid"} strokeWidth={1} />
                  <text x={-10} dy="0.32em" textAnchor="end" className="num-stable fill-muted-foreground text-[11.5px]">
                    {format(t)}
                  </text>
                </g>
              ))}
              {dates.map((d, i) =>
                i % xTickEvery === 0 || i === dates.length - 1 ? (
                  <text
                    key={d}
                    x={x(d)}
                    y={ih + 20}
                    textAnchor={i === 0 ? "start" : i === dates.length - 1 ? "end" : "middle"}
                    className="num-stable fill-muted-foreground text-[11.5px]"
                  >
                    {md(d)}
                  </text>
                ) : null,
              )}

              {hi !== null && <line x1={hi * step} x2={hi * step} y2={ih} className="stroke-foreground/25" strokeWidth={1} />}

              <g>
              {series.map((s) => {
                const dim = focusKey && focusKey !== s.key
                const d = s.points.map((p, i) => `${i ? "L" : "M"}${x(p.date)},${y(p.value)}`).join("")
                return (
                  <g key={s.key} className={cn("transition-opacity duration-200", dim && "opacity-15")}>
                    <path
                      d={d}
                      fill="none"
                      stroke={s.color}
                      strokeWidth={2}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                    {s.points.map((p) =>
                      p.day != null && dates.length <= 100 ? (
                        <circle key={"d" + p.date} cx={x(p.date)} cy={y(p.day)} r={2} fill={s.color} opacity={0.3} />
                      ) : null,
                    )}
                    {hi !== null &&
                      s.points
                        .filter((p) => p.date === dates[hi])
                        .map((p) => (
                          <circle key={p.date} cx={x(p.date)} cy={y(p.value)} r={4.5} fill={s.color} className="stroke-card" strokeWidth={2} />
                        ))}
                  </g>
                )
              })}

              </g>

              {labels.map((l) => (
                <text
                  key={l.key}
                  x={iw + 10}
                  y={l.y}
                  dy="0.32em"
                  className={cn(
                    "fill-foreground text-[12px] transition-opacity",
                    focusKey && focusKey !== l.key && "opacity-30",
                  )}
                >
                  <tspan fill={l.color}>━ </tspan>
                  {l.key.length > 9 ? l.key.slice(0, 9) + "…" : l.key}
                </text>
              ))}

              <rect
                width={iw + step / 2}
                x={-step / 4}
                height={ih}
                fill="transparent"
                onPointerMove={onMove}
                onPointerLeave={() => setHoverIdx(null)}
              />
            </g>
          </svg>
        )}

        {hi !== null && (
          <div
            role="status"
            className="pointer-events-none absolute top-2 z-10 min-w-[220px] rounded-lg border bg-popover/95 px-3 py-2.5 text-[12.5px] shadow-lg backdrop-blur-sm"
            style={tipOnLeft ? { right: width - tipLeft + 14 } : { left: tipLeft + 14 }}
          >
            <div className="mb-1.5 text-muted-foreground">
              {dates[hi]}
              {note && <span className="ml-2 text-[11.5px]">{note}</span>}
            </div>
            <ul className="space-y-1">
              {series
                .map((s, si) => ({ s, p: byDate[hi][si] }))
                // same top-to-bottom order as the lines at this date
                .sort((a, b) => (b.p?.value ?? -Infinity) - (a.p?.value ?? -Infinity))
                .map(({ s, p }) => {
                return (
                  <li key={s.key} className={cn("flex items-center gap-2", !p && "opacity-45")}>
                    <span aria-hidden className="h-[2px] w-3 shrink-0 rounded-full" style={{ background: s.color }} />
                    <span className="num-stable font-semibold">{p ? format(p.value) : "—"}</span>
                    <span className="truncate text-muted-foreground">{s.key}</span>
                    <span className="num-stable ml-auto pl-3 whitespace-nowrap text-muted-foreground">
                      {p?.n ? `当天 ${p.n} 单${p.day != null && dayLabel ? ` · ${format(p.day)}` : ""}` : ""}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
