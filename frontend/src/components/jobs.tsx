import { useState } from "react"
import { Play, ScrollText } from "lucide-react"
import { toast } from "sonner"
import { api, type Job, type Run, type RunStatus } from "@/lib/api"
import { useData, useNow } from "@/lib/hooks"
import { parseServerTime, relativeFuture } from "@/lib/time"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

const DOT: Record<RunStatus, string> = { ok: "bg-success", error: "bg-destructive", running: "bg-primary animate-pulse" }
const TEXT: Record<RunStatus, string> = { ok: "成功", error: "出错", running: "运行中" }

export function StatusDot({ status, className }: { status: RunStatus | null; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", status ? DOT[status] : "bg-idle", className)} />
}

/** The last N runs as thin ticks, oldest on the left; empty slots stay dim. */
export function RunTicks({ history, slots = 14 }: { history: Job["history"]; slots?: number }) {
  const h = history.slice(-slots)
  const errors = h.filter((r) => r.status === "error").length
  const label = h.length ? `最近 ${h.length} 次，${errors ? `${errors} 次出错` : "全部成功"}` : "还没有运行过"
  return (
    <span role="img" aria-label={label} title={label} className="flex h-4 items-end gap-[2px]">
      {Array.from({ length: slots - h.length }, (_, i) => (
        <span key={"p" + i} className="h-1.5 w-[3px] rounded-[1px] bg-idle" />
      ))}
      {h.map((r) => (
        <span key={r.id} className={cn("h-4 w-[3px] rounded-[1px]", DOT[r.status])} />
      ))}
    </span>
  )
}

/**
 * The scheduled jobs behind a page: when each runs next, how the last runs went, and a button to run it now.
 * Lives at the bottom of each page so the data above can always be traced to the job that produced it.
 */
export function JobPanel({ module, onRan, title = "定时任务" }: { module: string; onRan?: () => void; title?: string }) {
  const { data: jobs, refresh } = useData(() => api.get<Job[]>(`/jobs?module=${module}`), 3000)
  const now = useNow()
  const [logFor, setLogFor] = useState<Job | null>(null)
  const [starting, setStarting] = useState<string | null>(null)

  async function run(j: Job) {
    setStarting(j.name)
    try {
      await api.post(`/jobs/${j.name}/run`)
      toast.success(`已开始：${j.label}`)
      await refresh()
      const wait = setInterval(async () => {
        const list = await api.get<Job[]>(`/jobs?module=${module}`)
        if (!list.find((x) => x.name === j.name)?.running) {
          clearInterval(wait)
          onRan?.()
        }
      }, 2000)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setStarting(null)
    }
  }

  if (!jobs?.length) return null
  return (
    <section aria-label={title} className="mt-10">
      <h2 className="mb-2.5 text-[15px] font-semibold">{title}</h2>
      <ul className="divide-y overflow-hidden rounded-xl border bg-card">
        {jobs.map((j) => {
          const status = j.running ? "running" : (j.last?.status ?? null)
          return (
            <li
              key={j.name}
              className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-5 py-3 md:grid-cols-[auto_120px_minmax(0,1fr)_auto_auto_auto]"
            >
              <StatusDot status={status} />
              <span className="font-medium">
                {j.label}
                <span className="sr-only">，{status ? TEXT[status] : "未运行"}</span>
              </span>
              <span
                className={cn(
                  "col-span-2 col-start-2 row-start-2 truncate text-[13px] text-muted-foreground md:col-span-1 md:col-start-auto md:row-start-auto",
                  j.last?.status === "error" && !j.running && "text-destructive",
                )}
                title={j.last?.summary}
              >
                {j.running ? "运行中…" : j.last ? `${j.last.summary || TEXT[j.last.status]}` : "还没有运行过"}
              </span>
              <span className="num-stable hidden text-right text-[13px] text-muted-foreground md:block">
                {j.next_ts ? `下次 ${relativeFuture(j.next_ts, now)}` : "未启用"}
              </span>
              <span className="hidden md:block">
                <RunTicks history={j.history} />
              </span>
              <span className="row-span-2 flex items-center gap-0.5 md:row-span-1">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`${j.label} 运行记录`} onClick={() => setLogFor(j)}>
                      <ScrollText />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>运行记录</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`立即运行 ${j.label}`}
                      disabled={j.running || starting === j.name}
                      onClick={() => run(j)}
                    >
                      {j.running || starting === j.name ? <Spinner /> : <Play />}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>立即运行</TooltipContent>
                </Tooltip>
              </span>
            </li>
          )
        })}
      </ul>
      <RunLogDialog job={logFor} onClose={() => setLogFor(null)} />
    </section>
  )
}

function RunLogDialog({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const { data: runs } = useData(() => (job ? api.get<Run[]>(`/runs?job=${job.name}&limit=30`) : Promise.resolve([])), job ? 2000 : undefined, [job?.name])
  const [open, setOpen] = useState<number | null>(null)
  return (
    <Dialog open={!!job} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85dvh] overflow-hidden sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{job?.label} · 运行记录</DialogTitle>
          <DialogDescription>最近 30 次，点一行展开完整输出。</DialogDescription>
        </DialogHeader>
        <ul className="-mx-6 max-h-[60dvh] divide-y overflow-auto border-y">
          {runs?.length === 0 && <li className="px-6 py-8 text-center text-muted-foreground">还没有运行记录</li>}
          {runs?.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => setOpen(open === r.id ? null : r.id)}
                aria-expanded={open === r.id}
                className="grid w-full grid-cols-[auto_132px_minmax(0,1fr)] items-center gap-3 px-6 py-2.5 text-left text-[13px] hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
              >
                <StatusDot status={r.status} />
                <span className="num-stable text-muted-foreground">{r.started_at.slice(5, 16)}</span>
                <span className={cn("truncate", r.status === "error" && "text-destructive")}>{r.summary || TEXT[r.status]}</span>
              </button>
              {open === r.id && (
                <pre className="max-h-72 overflow-auto bg-code px-6 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
                  {r.log || "（没有输出）"}
                  {r.finished_at ? `\n\n耗时 ${Math.max(0, Math.round(parseServerTime(r.finished_at) - parseServerTime(r.started_at)))} 秒` : ""}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
