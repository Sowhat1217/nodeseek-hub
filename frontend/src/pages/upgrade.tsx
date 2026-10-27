import { useState } from "react"
import { ArrowUpRight, Inbox, MessageSquareText, PenLine } from "lucide-react"
import { toast } from "sonner"
import { api, nsLink, type Draft, type UpgradeStatus } from "@/lib/api"
import { useData } from "@/lib/hooks"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import { JobPanel } from "@/components/jobs"
import { useConfirm } from "@/components/confirm"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Spinner } from "@/components/ui/spinner"
import { Skeleton } from "@/components/ui/skeleton"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"

const CAT: Record<string, string> = {
  daily: "日常", tech: "技术", info: "情报", review: "测评", trade: "交易", carpool: "拼车",
  promotion: "推广", life: "生活", dev: "Dev", "photo-share": "贴图", expose: "曝光", sandbox: "沙盒",
}

export default function UpgradePage() {
  const [tab, setTab] = useState<"pending" | "done">("pending")
  const status = useData(() => api.get<UpgradeStatus>("/upgrade"), 30000)
  const drafts = useData(() => api.get<Draft[]>(`/drafts?status=${tab}`), 15000, [tab])
  const pending = useData(() => api.get<Draft[]>("/drafts?status=pending"), 15000)
  const reload = () => {
    status.refresh()
    drafts.refresh()
    pending.refresh()
  }

  return (
    <>
      <PageHeader title="升级" description="签到按时自动完成。帖子和评论由 LLM 写成草稿，你看过、改过，点发布才会发到 NodeSeek。" />

      {status.data && !status.data.has_account && (
        <p role="alert" className="mb-6 rounded-lg border border-warning/40 bg-warning/8 px-4 py-2.5 text-[13px]">
          还没有填 NodeSeek 账号，签到和发布都要用它登录。去 <a href="#/settings" className="font-medium underline underline-offset-4">设置</a> 里填写。
        </p>
      )}

      {status.data ? <CheckinPanel s={status.data} /> : <Skeleton className="h-[148px] rounded-xl" />}

      <section aria-labelledby="drafts-title" className="mt-10">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="drafts-title" className="text-[15px] font-semibold">
            草稿
          </h2>
          <Segmented
            label="草稿状态"
            value={tab}
            onChange={setTab}
            options={[
              { id: "pending", label: `待发布${pending.data?.length ? ` ${pending.data.length}` : ""}` },
              { id: "done", label: "已处理" },
            ]}
          />
        </div>
        {!drafts.data ? (
          <Skeleton className="h-[240px] rounded-xl" />
        ) : drafts.data.length === 0 ? (
          <Empty className="rounded-xl border border-dashed bg-card py-14">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Inbox />
              </EmptyMedia>
              <EmptyTitle>{tab === "pending" ? "没有待发布的草稿" : "还没有处理过草稿"}</EmptyTitle>
              <EmptyDescription>
                {tab === "pending"
                  ? "到了设置里的发帖、评论时间，LLM 会写好草稿放在这里。想现在就写一条，点下方任务的运行按钮。"
                  : "发布或放弃的草稿会出现在这里。"}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : tab === "pending" ? (
          <ul className="space-y-4">
            {drafts.data.map((d) => (
              <DraftCard key={d.id} d={d} onDone={reload} />
            ))}
          </ul>
        ) : (
          <DoneList drafts={drafts.data} />
        )}
      </section>

      <JobPanel module="upgrade" onRan={reload} />
    </>
  )
}

function CheckinPanel({ s }: { s: UpgradeStatus }) {
  const days = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(Date.now() - (29 - i) * 86400000)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
    return { key, c: s.checkins.find((c) => c.day === key) }
  })
  const done = s.today?.ok
  const posts = (s.today_counts.post_pending ?? 0) + (s.today_counts.post_published ?? 0)
  const comments = (s.today_counts.comment_pending ?? 0) + (s.today_counts.comment_published ?? 0)
  return (
    <section aria-label="签到" className="grid gap-6 rounded-xl border bg-card p-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:p-6">
      <div className="min-w-0">
        <div className="flex items-baseline gap-3">
          <span className={cn("size-2.5 shrink-0 self-center rounded-full", done ? "bg-success" : s.today ? "bg-destructive" : "bg-idle")} aria-hidden />
          <p className="text-xl font-semibold tracking-tight">{done ? "今天已签到" : s.today ? "今天签到失败" : "今天还没签到"}</p>
          <p className="num-stable text-[13px] text-muted-foreground">
            连续 <span className="font-semibold text-foreground">{s.streak}</span> 天
          </p>
        </div>
        <p className="mt-1.5 truncate pl-5.5 text-[13px] text-muted-foreground">
          {s.today ? `${s.today.at.slice(11, 16)} · ${s.today.message}` : "到了设置里的签到时间会自动完成。"}
        </p>
        <p className="num-stable mt-4 pl-5.5 text-[13px] text-muted-foreground">
          今天写了 <span className="text-foreground">{posts}</span> 篇帖子草稿、<span className="text-foreground">{comments}</span> 条评论草稿 · 已发布{" "}
          <span className="text-foreground">{(s.today_counts.post_published ?? 0) + (s.today_counts.comment_published ?? 0)}</span>
        </p>
      </div>
      <div>
        <div className="grid grid-cols-[repeat(15,14px)] gap-1" role="img" aria-label={`最近 30 天签到 ${s.checkins.filter((c) => c.ok).length} 天`}>
          {days.map(({ key, c }) => (
            <span
              key={key}
              title={`${key}：${c ? (c.ok ? c.message : "失败") : "未签到"}`}
              className={cn("size-3.5 rounded-[3px]", c ? (c.ok ? "bg-success/85" : "bg-destructive/80") : "bg-idle")}
            />
          ))}
        </div>
        <p className="mt-2 flex justify-between text-[11.5px] text-muted-foreground">
          <span>30 天前</span>
          <span>今天</span>
        </p>
      </div>
    </section>
  )
}

function DraftCard({ d, onDone }: { d: Draft; onDone: () => void }) {
  const [title, setTitle] = useState(d.title ?? "")
  const [content, setContent] = useState(d.content)
  const [busy, setBusy] = useState<"publish" | "discard" | null>(null)
  const confirm = useConfirm()
  const dirty = title !== (d.title ?? "") || content !== d.content
  const isPost = d.kind === "post"

  async function save() {
    await api.put(`/drafts/${d.id}`, { title: isPost ? title : null, content })
  }
  async function publish() {
    const ok = await confirm({
      title: isPost ? "把这篇帖子发到 NodeSeek？" : "把这条评论发到 NodeSeek？",
      description: isPost ? `「${title}」会发在${CAT[d.category ?? ""] ?? d.category}板块，用你的账号公开发布。` : `会回复在《${d.target_title}》下，用你的账号公开发布。`,
      action: "发布",
      variant: "default",
    })
    if (!ok) return
    setBusy("publish")
    try {
      if (dirty) await save()
      await api.post(`/drafts/${d.id}/publish`)
      toast.success("已发布")
      onDone()
    } catch (e) {
      toast.error("发布失败", { description: (e as Error).message, duration: 12000 })
      onDone()
    } finally {
      setBusy(null)
    }
  }
  async function discard() {
    setBusy("discard")
    try {
      await api.post(`/drafts/${d.id}/discard`)
      toast("已放弃这条草稿")
      onDone()
    } finally {
      setBusy(null)
    }
  }

  return (
    <li className="animate-rise rounded-xl border bg-card">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-5 py-3 text-[13px] text-muted-foreground">
        {isPost ? <PenLine className="size-4" /> : <MessageSquareText className="size-4" />}
        <span className="font-medium text-foreground">{isPost ? "帖子" : "评论"}</span>
        {isPost ? (
          <span>发在{CAT[d.category ?? ""] ?? d.category}</span>
        ) : (
          d.target_id && (
            <a
              href={nsLink(d.target_id)}
              target="_blank"
              rel="noreferrer"
              className="order-last flex min-w-0 basis-full items-center gap-1 hover:text-foreground sm:order-none sm:basis-auto"
            >
              <span className="shrink-0">回复</span> <span className="max-w-[40ch] truncate">《{d.target_title}》</span>
              <ArrowUpRight className="size-3.5" />
            </a>
          )
        )}
        <span className="num-stable ml-auto">{d.created_at.slice(5, 16)}</span>
        {d.status === "failed" && <span className="w-full text-destructive">上次发布失败：{d.result}</span>}
      </div>
      <div className="space-y-3 px-5 pt-4 pb-3">
        {isPost && (
          <Input aria-label="标题" value={title} onChange={(e) => setTitle(e.target.value)} className="text-[15px] font-medium" />
        )}
        <Textarea
          aria-label="内容"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className={cn("leading-relaxed", isPost ? "min-h-[180px]" : "min-h-[84px]")}
        />
        {d.source && <p className="text-[12.5px] text-muted-foreground">依据：{d.source}</p>}
      </div>
      <div className="flex items-center justify-end gap-2 px-5 pb-4">
        {dirty && (
          <Button
            variant="ghost"
            className="mr-auto"
            onClick={async () => {
              await save()
              toast.success("改动已保存")
              onDone()
            }}
          >
            保存改动
          </Button>
        )}
        <Button variant="outline" onClick={discard} disabled={!!busy}>
          {busy === "discard" && <Spinner />}
          放弃
        </Button>
        <Button onClick={publish} disabled={!!busy || !content.trim() || (isPost && !title.trim())}>
          {busy === "publish" && <Spinner />}
          发布
        </Button>
      </div>
    </li>
  )
}

const DONE_TEXT: Record<string, string> = { published: "已发布", failed: "发布失败", discarded: "已放弃" }

function DoneList({ drafts }: { drafts: Draft[] }) {
  return (
    <ul className="divide-y overflow-hidden rounded-xl border bg-card">
      {drafts.map((d) => (
        <li key={d.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-3 px-5 py-3">
          <span
            className={cn(
              "size-2 self-center rounded-full",
              d.status === "published" ? "bg-success" : d.status === "failed" ? "bg-destructive" : "bg-idle",
            )}
            aria-hidden
          />
          <span className="min-w-0">
            <span className="block truncate font-medium">{d.kind === "post" ? d.title : `回复《${d.target_title}》`}</span>
            <span className={cn("block truncate text-[13px] text-muted-foreground", d.status === "failed" && "text-destructive")}>
              {DONE_TEXT[d.status]}
              {d.result && d.result !== "手动放弃" ? ` · ${d.result}` : ""}
            </span>
          </span>
          <span className="num-stable text-[13px] text-muted-foreground">{(d.published_at ?? d.created_at).slice(5, 16)}</span>
        </li>
      ))}
    </ul>
  )
}
