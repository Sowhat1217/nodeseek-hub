import { useState } from "react"
import { useWidth } from "@/lib/hooks"
import { cn } from "@/lib/utils"

export interface Stack {
  label: string // x label, e.g. "14"
  title: string // tooltip heading
  parts: { key: string; value: number }[]
}

const H = 168
const GAP = 2

/** Columns stacked by category. Each column is its own hover target (full height, not just the painted part). */
export function StackedColumns({
  data,
  colors,
  names,
  ariaLabel,
}: {
  data: Stack[]
  colors: Record<string, string>
  names: Record<string, string>
  ariaLabel: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...data.map((d) => d.parts.reduce((a, p) => a + p.value, 0)))
  const ih = H - 22
  const colW = data.length ? width / data.length : 0
  const barW = Math.max(3, Math.min(22, colW - 4))
  const keys = Object.keys(colors)

  return (
    <div ref={ref} className="relative" style={{ height: H }}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label={ariaLabel}>
          <line x2={width} y1={ih + 0.5} y2={ih + 0.5} className="stroke-border" />
          {data.map((d, i) => {
            let acc = 0
            const cx = i * colW + colW / 2
            const ordered = keys.map((k) => d.parts.find((p) => p.key === k)).filter((p): p is { key: string; value: number } => !!p && p.value > 0)
            return (
              <g
                key={i}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
                className={cn("transition-opacity duration-150", hover !== null && hover !== i && "opacity-45")}
              >
                <rect x={i * colW} width={colW} height={ih} fill="transparent" />
                {ordered.map((p, j) => {
                  const h = (p.value / max) * ih
                  const top = ih - acc - h
                  acc += h
                  const isTop = j === ordered.length - 1
                  const segH = Math.max(0, h - (isTop ? 0 : GAP))
                  return (
                    <path
                      key={p.key}
                      d={roundedTop(cx - barW / 2, top, barW, segH, isTop ? Math.min(3, barW / 2, segH) : 0)}
                      fill={colors[p.key]}
                      className="origin-bottom animate-tick-in"
                      style={{ animationDelay: `${i * 18}ms` }}
                    />
                  )
                })}
                {i % Math.ceil(data.length / Math.max(4, Math.floor(width / 42))) === 0 && (
                  <text x={cx} y={H - 4} textAnchor="middle" className="num-stable fill-muted-foreground text-[11px]">
                    {d.label}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && data[hover] && (
        <div
          role="status"
          className="pointer-events-none absolute bottom-7 z-10 min-w-[136px] rounded-lg border bg-popover/95 px-3 py-2 text-[12.5px] shadow-lg backdrop-blur-sm"
          style={hover * colW > width * 0.6 ? { right: width - hover * colW + 6 } : { left: hover * colW + colW + 6 }}
        >
          <div className="mb-1 flex items-baseline justify-between gap-3 text-muted-foreground">
            {data[hover].title}
            <span className="num-stable font-semibold text-foreground">{data[hover].parts.reduce((a, p) => a + p.value, 0)} 帖</span>
          </div>
          <ul className="space-y-0.5">
            {keys
              .map((k) => data[hover].parts.find((p) => p.key === k))
              .filter((p) => p && p.value > 0)
              .map((p) => (
                <li key={p!.key} className="flex items-center gap-2">
                  <span aria-hidden className="size-2 rounded-[2px]" style={{ background: colors[p!.key] }} />
                  <span className="text-muted-foreground">{names[p!.key] ?? p!.key}</span>
                  <span className="num-stable ml-auto font-medium">{p!.value}</span>
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  if (h <= 0) return ""
  if (!r) return `M${x},${y}h${w}v${h}h${-w}z`
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}z`
}
