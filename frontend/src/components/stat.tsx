import type { ReactNode } from "react"
import { useCountUp } from "@/lib/hooks"
import { cn } from "@/lib/utils"

/** A row of figures sharing one frame, separated by hairlines rather than chopped into cards. */
export function StatStrip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl
      className={cn(
        "grid grid-cols-2 overflow-hidden rounded-xl border bg-card md:grid-cols-4",
        "[&>div]:border-border [&>div:nth-child(odd)]:border-r md:[&>div]:border-r md:[&>div:last-child]:border-r-0",
        "[&>div:nth-child(-n+2)]:border-b md:[&>div:nth-child(-n+2)]:border-b-0",
        className,
      )}
    >
      {children}
    </dl>
  )
}

export function Stat({
  label,
  value,
  format = (v) => Math.round(v).toLocaleString("zh-CN"),
  delta,
  deltaLabel = "较上期",
  hint,
  goodWhenUp,
}: {
  label: string
  value: number | null
  format?: (v: number) => string
  /** percent change vs the previous period */
  delta?: number | null
  deltaLabel?: string
  hint?: ReactNode
  /** colour the delta: undefined = neutral (a premium going up is not "good" or "bad") */
  goodWhenUp?: boolean
}) {
  const v = useCountUp(value)
  const up = (delta ?? 0) > 0
  const tone =
    delta === null || delta === undefined || goodWhenUp === undefined || Math.abs(delta) < 0.5
      ? "text-muted-foreground"
      : up === goodWhenUp
        ? "text-success"
        : "text-destructive"
  return (
    <div className="flex min-w-0 flex-col gap-1.5 px-5 py-4">
      <dt className="text-[13px] text-muted-foreground">{label}</dt>
      <dd className="num-stable text-[26px] leading-none font-semibold tracking-tight">{v === null ? "—" : format(v)}</dd>
      <dd className="min-h-[18px] truncate text-[12.5px] text-muted-foreground">
        {delta !== null && delta !== undefined ? (
          <>
            <span className={cn("num-stable font-medium", tone)}>
              {up ? "↑" : delta < 0 ? "↓" : ""}
              {Math.abs(delta).toFixed(Math.abs(delta) < 10 ? 1 : 0)}%
            </span>{" "}
            {deltaLabel}
          </>
        ) : (
          hint
        )}
      </dd>
    </div>
  )
}
