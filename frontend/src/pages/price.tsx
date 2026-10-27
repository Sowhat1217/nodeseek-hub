import { useState } from "react"
import { ArrowUpRight, TrendingUp } from "lucide-react"
import { api, nsLink, type PriceOverview } from "@/lib/api"
import { useData } from "@/lib/hooks"
import { md, pctChange, yuan } from "@/lib/format"
import { cn } from "@/lib/utils"
import { PageHeader } from "@/components/page-header"
import { Segmented } from "@/components/segmented"
import { Stat, StatStrip } from "@/components/stat"
import { LineChart } from "@/components/charts/line-chart"
import { JobPanel } from "@/components/jobs"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"

const RANGES = [
  { id: "7", label: "7 天" },
  { id: "30", label: "30 天" },
] as const
const COLORS = [1, 2, 3, 4, 5, 6].map((i) => `var(--series-${i})`)

export default function PricePage() {
  const [days, setDays] = useState<"7" | "30">("7")
  const [merchant, setMerchant] = useState("all")
  const { data, loading, refresh } = useData(
    () => api.get<PriceOverview>(`/price?days=${days}` + (merchant !== "all" ? `&merchant=${encodeURIComponent(merchant)}` : "")),
    undefined,
    [days, merchant],
  )

  return (
    <>
      <PageHeader
        title="价格走势"
        description="交易区成交帖的溢价：在剩余价值之上多付的钱。每晚抓取，由 LLM 归一成商家和型号。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="时间范围" value={days} onChange={setDays} options={[...RANGES]} />
            <Select value={merchant} onValueChange={setMerchant}>
              <SelectTrigger className="w-[148px] bg-card" aria-label="按商家筛选">
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectItem value="all">全部商家</SelectItem>
                {data?.merchants.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
      />

      {!data ? (
        <div className="space-y-6">
          <Skeleton className="h-[104px] rounded-xl" />
          <Skeleton className="h-[400px] rounded-xl" />
        </div>
      ) : data.kpi.posts === 0 ? (
        <Empty className="rounded-xl border border-dashed bg-card py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <TrendingUp />
            </EmptyMedia>
            <EmptyTitle>还没有交易区数据</EmptyTitle>
            <EmptyDescription>
              每晚定时抓取一次。想马上看到结果，点下方「抓取交易区」右边的运行按钮，首次会取最近几页。
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className={cn("space-y-6 transition-opacity", loading && "opacity-60")}>
          <StatStrip>
            <Stat label="成交" value={data.kpi.deals} delta={pctChange(data.kpi.deals, data.kpi.deals_prev)} deltaLabel={`较前 ${days} 天`} />
            <Stat
              label="溢价中位数"
              value={data.kpi.median}
              format={(v) => yuan(v)}
              delta={pctChange(data.kpi.median, data.kpi.median_prev)}
              deltaLabel={`较前 ${days} 天`}
            />
            <Stat label="交易区帖子" value={data.kpi.posts} hint={`成交率 ${data.kpi.posts ? ((data.kpi.deals / data.kpi.posts) * 100).toFixed(1) : 0}%`} />
            <Stat
              label="写了溢价的成交"
              value={data.kpi.priced}
              hint={data.kpi.deals ? `占成交的 ${Math.round((data.kpi.priced / data.kpi.deals) * 100)}%，其余没写价格` : "—"}
            />
          </StatStrip>

          <section aria-labelledby="trend-title" className="rounded-xl border bg-card p-5 md:p-6">
            <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 id="trend-title" className="text-base font-semibold">
                溢价走势
              </h2>
              <p className="text-[13px] text-muted-foreground">
                {data.window > 1 ? `线是 ${data.window} 日滚动中位数，淡点是当天中位数` : "每天的成交溢价中位数"} · 成交最多的 {data.series.length} 个型号
              </p>
            </div>
            {data.series.length ? (
              <LineChart
                dates={data.dates}
                ariaLabel={`最近 ${days} 天各型号成交溢价中位数走势`}
                note={data.window > 1 ? `${data.window} 日滚动中位数` : undefined}
                format={(v) => yuan(v)}
                series={data.series.map((s, i) => ({
                  key: s.key,
                  color: COLORS[i],
                  points: s.points,
                }))}
              />
            ) : (
              <p className="py-16 text-center text-sm text-muted-foreground">这段时间没有写了溢价的成交。</p>
            )}
            <DailyStrip daily={data.daily} />
          </section>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <HeatList heat={data.heat} />
            <DealList deals={data.deals} />
          </div>
        </div>
      )}

      <JobPanel module="price" onRan={refresh} />
    </>
  )
}

/** Deals per day as a quiet strip under the chart: volume context without a second y-axis. */
function DailyStrip({ daily }: { daily: PriceOverview["daily"] }) {
  const max = Math.max(1, ...daily.map((d) => d.deals))
  return (
    <div className="mt-5 border-t pt-4">
      <div className="mb-2 flex items-baseline justify-between text-[12.5px] text-muted-foreground">
        <span>每日成交数</span>
        <span className="num-stable">最多 {max} 单</span>
      </div>
      <div className="flex h-8 items-end gap-[2px]" role="img" aria-label="每日成交数">
        {daily.map((d) => (
          <span
            key={d.date}
            title={`${d.date}：${d.deals} 单${d.median !== null ? `，中位数 ${yuan(d.median)}` : ""}`}
            className="min-w-[2px] flex-1 rounded-t-[2px] bg-foreground/15 transition-colors hover:bg-foreground/45"
            style={{ height: `${Math.max(d.deals ? 8 : 3, (d.deals / max) * 100)}%` }}
          />
        ))}
      </div>
    </div>
  )
}

function HeatList({ heat }: { heat: PriceOverview["heat"] }) {
  const max = Math.max(1, ...heat.map((h) => h.posts))
  return (
    <section aria-labelledby="heat-title" className="flex flex-col rounded-xl border bg-card">
      <div className="flex items-baseline justify-between px-5 pt-5 pb-3">
        <h2 id="heat-title" className="text-base font-semibold">
          热门型号
        </h2>
        <span className="text-[13px] text-muted-foreground">按出现次数</span>
      </div>
      {heat.length === 0 ? (
        <p className="px-5 pb-8 text-sm text-muted-foreground">还没有识别出商家。</p>
      ) : (
        // rows share the card's height, so it matches the deals list next to it instead of leaving a gap
        <ol className="flex flex-1 flex-col pb-2">
          {heat.map((h, i) => (
            <li key={`${h.merchant}-${h.model}`} className="group relative flex flex-1 flex-col justify-center px-5 py-2.5">
              <div className="flex items-baseline gap-3">
                <span className="num-stable w-5 shrink-0 text-right text-[13px] text-muted-foreground">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{h.merchant}</span>
                  {h.model && <span className="text-muted-foreground"> {h.model}</span>}
                </span>
                <span className="num-stable shrink-0 text-[13px]">
                  {h.posts}
                  <span className="text-muted-foreground"> 帖 · {h.deals} 成交</span>
                </span>
              </div>
              <div className="mt-1.5 ml-8 h-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="animate-grow-x h-full rounded-full bg-foreground/70 transition-colors group-hover:bg-foreground"
                  style={{ width: `${(h.posts / max) * 100}%`, animationDelay: `${i * 40}ms` }}
                />
              </div>
              <p className="sr-only">
                浏览 {h.views}，回复 {h.replies}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function DealList({ deals }: { deals: PriceOverview["deals"] }) {
  return (
    <section aria-labelledby="deals-title" className="flex flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex items-baseline justify-between px-5 pt-5 pb-3">
        <h2 id="deals-title" className="text-base font-semibold">
          最近成交
        </h2>
        <span className="num-stable text-[13px] text-muted-foreground">共 {deals.length} 单</span>
      </div>
      {deals.length === 0 ? (
        <p className="px-5 pb-8 text-sm text-muted-foreground">这段时间没有识别到成交。</p>
      ) : (
        // the list scrolls inside the card; its height follows the hot-models card next to it
        <div className="relative min-h-[480px] flex-1 border-t">
          <ul className="absolute inset-0 divide-y overflow-y-auto overscroll-contain">
            {deals.map((d) => (
              <li key={d.post_id}>
                <a
                  href={nsLink(d.post_id)}
                  target="_blank"
                  rel="noreferrer"
                  className="group grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-x-3 px-5 py-2.5 transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                  title={d.llm_note ?? undefined}
                >
                  <span className="num-stable text-[13px] text-muted-foreground">{md(d.deal_date)}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {[d.merchant, d.model].filter(Boolean).join(" ") || "未识别"}
                    </span>
                    <span className="flex items-center gap-1 truncate text-[12.5px] text-muted-foreground">
                      <span className="truncate">{d.title}</span>
                      <ArrowUpRight className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                    </span>
                  </span>
                  <span className="text-right">
                    {d.premium_cny != null ? (
                      <span
                        className="num-stable block font-semibold"
                        title={d.premium_est ? `按剩余价值估算${d.price_cny != null ? `（总价 ${yuan(d.price_cny)}）` : ""}` : undefined}
                      >
                        {d.premium_est ? "≈" : ""}
                        {yuan(d.premium_cny, true)}
                      </span>
                    ) : d.price_cny != null ? (
                      <span className="num-stable block text-muted-foreground">总价 {yuan(d.price_cny)}</span>
                    ) : (
                      <span className="block text-muted-foreground">未写价</span>
                    )}
                    {d.premium_est && d.price_cny != null ? (
                      <span className="num-stable text-[12px] text-muted-foreground">总价 {yuan(d.price_cny)}</span>
                    ) : (
                      d.currency === "USD" &&
                      d.premium !== null && <span className="num-stable text-[12px] text-muted-foreground">${d.premium}</span>
                    )}
                    {d.discount !== null && <span className="text-[12px] text-muted-foreground">{d.discount * 10} 折</span>}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
