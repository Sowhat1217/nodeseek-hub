import { useEffect, useState, type FormEvent } from "react"
import { BellOff, Send } from "lucide-react"
import { toast } from "sonner"
import { api, type NotifyConfig } from "@/lib/api"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Spinner } from "@/components/ui/spinner"
import { Skeleton } from "@/components/ui/skeleton"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"

const HINT: Record<string, string> = {
  price: "每晚抓取后：新帖数、成交数、成交溢价和当天热门商家",
  hot: "每天一次：24 小时热度关键词和一句话总结",
  checkin: "每次签到的结果，包括失败原因",
  drafts: "LLM 写好帖子或评论草稿时提醒你去发布",
  errors: "任何定时任务从正常变成出错时提醒一次，之后连续出错不重复",
}
// shown in the token box when a token is saved; never sent back to the server
const MASK = "\u2022".repeat(30)

const MODULE_NAME: Record<string, string> = { test: "测试", price: "价格", hot: "热度", checkin: "签到", drafts: "草稿", errors: "出错" }

export default function NotifyPage() {
  const [cfg, setCfg] = useState<NotifyConfig | null>(null)
  const [token, setToken] = useState("")
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = () =>
    api.get<NotifyConfig>("/notify").then((c) => {
      setCfg(c)
      setToken((t) => (t && t !== MASK ? t : c.has_token ? MASK : ""))
    })
  useEffect(() => {
    load()
  }, [])

  async function save(e?: FormEvent, next = cfg) {
    e?.preventDefault()
    if (!next) return false
    setSaving(true)
    try {
      await api.put("/notify", { tg_api: next.tg_api, tg_chat_id: next.tg_chat_id, tg_token: token && token !== MASK ? token : null, modules: next.modules })
      if (token && token !== MASK) setCfg({ ...next, has_token: true })
      setToken(token ? MASK : "")
      if (e) toast.success("通知设置已保存")
      return true
    } catch (err) {
      toast.error((err as Error).message)
      return false
    } finally {
      setSaving(false)
    }
  }

  async function test() {
    if (!(await save())) return
    setTesting(true)
    try {
      await api.post("/notify/test")
      toast.success("测试消息已发出", { description: "去 Telegram 看看有没有收到。" })
    } catch (err) {
      toast.error("测试消息没发出去", { description: (err as Error).message, duration: 15000 })
    } finally {
      setTesting(false)
      load()
    }
  }

  async function toggle(k: string, v: boolean) {
    if (!cfg) return
    const next = { ...cfg, modules: { ...cfg.modules, [k]: v } }
    setCfg(next)
    await save(undefined, next)
  }

  if (!cfg) return <Skeleton className="h-[480px] rounded-xl" />

  return (
    <>
      <PageHeader title="通知" description="通过你自己的 Telegram 机器人推送。每类消息可以单独开关。" />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section aria-labelledby="tg-title" className="rounded-xl border bg-card p-5 md:p-6">
          <h2 id="tg-title" className="mb-5 text-base font-semibold">
            Telegram 机器人
          </h2>
          <form onSubmit={save} noValidate>
            <FieldGroup className="gap-5">
              <Field>
                <FieldLabel htmlFor="tg-token">Bot Token</FieldLabel>
                <Input
                  id="tg-token"
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  onFocus={(e) => token === MASK && e.target.select()}
                  placeholder="123456789:AA…"
                />
                <FieldDescription>找 @BotFather 新建机器人后复制。保存后加密存储。</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="tg-chat">Chat ID</FieldLabel>
                <Input
                  id="tg-chat"
                  inputMode="numeric"
                  className="num-stable"
                  value={cfg.tg_chat_id}
                  onChange={(e) => setCfg({ ...cfg, tg_chat_id: e.target.value })}
                />
                <FieldDescription>私聊填你自己的用户 ID；群聊填群 ID（以 -100 开头），并先把机器人拉进群。</FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="tg-api">API 地址</FieldLabel>
                <Input id="tg-api" value={cfg.tg_api} onChange={(e) => setCfg({ ...cfg, tg_api: e.target.value })} />
                <FieldDescription>服务器连不上 api.telegram.org 时，换成你的反代地址。</FieldDescription>
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={saving || testing}>
                  {saving && !testing && <Spinner />}
                  保存
                </Button>
                <Button type="button" variant="outline" onClick={test} disabled={saving || testing || !token || !cfg.tg_chat_id}>
                  {testing ? <Spinner /> : <Send />}
                  保存并发测试消息
                </Button>
              </div>
            </FieldGroup>
          </form>
        </section>

        <section aria-labelledby="mods-title" className="rounded-xl border bg-card">
          <h2 id="mods-title" className="px-5 pt-5 pb-3 text-base font-semibold md:px-6 md:pt-6">
            推送哪些消息
          </h2>
          <ul className="divide-y border-t">
            {Object.entries(cfg.labels).map(([k, label]) => (
              <li key={k}>
                <label htmlFor={`m-${k}`} className="flex cursor-pointer items-center gap-4 px-5 py-3.5 transition-colors hover:bg-accent/40 md:px-6">
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{label}</span>
                    <span className="block text-[13px] text-muted-foreground">{HINT[k]}</span>
                  </span>
                  <Switch id={`m-${k}`} checked={!!cfg.modules[k]} onCheckedChange={(v) => toggle(k, v)} />
                </label>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section aria-labelledby="hist-title" className="mt-10">
        <h2 id="hist-title" className="mb-2.5 text-[15px] font-semibold">
          最近发出的消息
        </h2>
        {cfg.history.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card py-12 text-center text-sm text-muted-foreground">
            <BellOff className="size-5" />
            还没有发过消息。配置好机器人后点「保存并发测试消息」。
          </div>
        ) : (
          <ul className="divide-y overflow-hidden rounded-xl border bg-card">
            {cfg.history.map((h) => (
              <li key={h.id} className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 px-5 py-3 md:grid-cols-[auto_112px_56px_minmax(0,1fr)]">
                <span className={cn("mt-2 size-2 rounded-full", h.ok ? "bg-success" : "bg-destructive")} aria-label={h.ok ? "已送达" : "发送失败"} />
                <span className="num-stable text-[13px] text-muted-foreground md:pt-px">{h.at.slice(5, 16)}</span>
                <span className="col-start-2 text-[13px] text-muted-foreground md:col-start-auto md:pt-px">{MODULE_NAME[h.module] ?? h.module}</span>
                <span className="col-start-2 min-w-0 md:col-start-auto">
                  <span className="line-clamp-2 text-[13.5px] whitespace-pre-line">{h.text}</span>
                  {!h.ok && <span className="block text-[13px] text-destructive">{h.error}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
