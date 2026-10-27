import { cn } from "@/lib/utils"

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T
  onChange: (v: T) => void
  options: { id: T; label: string }[]
  label: string
  className?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("relative flex h-9 items-center gap-0.5 rounded-lg bg-muted p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.id}
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className="h-8 rounded-md px-3 text-[13px] whitespace-nowrap text-muted-foreground transition-all hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none aria-checked:bg-card aria-checked:text-foreground aria-checked:shadow-sm"
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
