import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"))
const p2 = (n: number) => String(n).padStart(2, "0")

/** 24-hour HH:MM picker: hour column + minute column (5-minute steps, plus the current value). */
export function TimePicker({
  value,
  onChange,
  label = "时间",
  className,
}: {
  value: string
  onChange: (v: string) => void
  label?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [h, m] = (value || "00:00").split(":")
  const minutes = Array.from({ length: 12 }, (_, i) => p2(i * 5))
  if (!minutes.includes(m)) minutes.push(m), minutes.sort()

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${label}：${value}`}
          className={cn(
            "num-stable flex h-8 w-[88px] items-center justify-center rounded-md border border-input bg-background px-2 text-sm shadow-xs transition-[color,box-shadow] outline-none",
            "hover:bg-accent/50 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=open]:border-ring data-[state=open]:ring-[3px] data-[state=open]:ring-ring/50",
            className,
          )}
        >
          {value}
        </button>
      </PopoverTrigger>
      <PopoverContent align="center" className="w-auto p-1.5">
        <div className="flex gap-1.5">
          <Column label="时" items={HOURS} value={h} onPick={(v) => onChange(`${v}:${m}`)} />
          <div className="w-px bg-border" />
          <Column
            label="分"
            items={minutes}
            value={m}
            onPick={(v) => {
              onChange(`${h}:${v}`)
              setOpen(false)
            }}
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}

function Column({ label, items, value, onPick }: { label: string; items: string[]; value: string; onPick: (v: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  // open with the selected item in view
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>("[aria-selected=true]")
    if (el && ref.current) ref.current.scrollTop = el.offsetTop - ref.current.clientHeight / 2 + el.clientHeight / 2
  }, [])
  return (
    <div>
      <div className="px-2 pb-1 text-center text-[11.5px] text-muted-foreground">{label}</div>
      {/* 92px top/bottom padding = (216 - 32) / 2: lets any item, even the first or last, sit on the middle row */}
      <div ref={ref} role="listbox" aria-label={label} className="relative h-[216px] w-12 overflow-y-auto overscroll-contain py-[92px] [scrollbar-width:none]">
        {items.map((it) => (
          <button
            key={it}
            type="button"
            role="option"
            aria-selected={it === value}
            onClick={() => onPick(it)}
            className="num-stable block h-8 w-full rounded-sm text-sm transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none aria-selected:bg-primary aria-selected:text-primary-foreground"
          >
            {it}
          </button>
        ))}
      </div>
    </div>
  )
}
