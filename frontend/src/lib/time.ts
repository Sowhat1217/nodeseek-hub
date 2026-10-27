const p2 = (n: number) => String(n).padStart(2, "0")

/** "12 秒后" / "3 分钟后" / "2 小时后" / "明天 12:30" */
export function relativeFuture(ts: number, now: number) {
  const d = ts - now
  if (d < 1) return "即将运行"
  if (d < 60) return `${Math.ceil(d)} 秒后`
  if (d < 3600) return `${Math.round(d / 60)} 分钟后`
  if (d < 48 * 3600) return `${Math.round(d / 3600)} 小时后`
  return `${Math.round(d / 86400)} 天后`
}

export function clock(ts: number, withSec = false) {
  const t = new Date(ts * 1000)
  return `${p2(t.getHours())}:${p2(t.getMinutes())}` + (withSec ? `:${p2(t.getSeconds())}` : "")
}

export function dayLabel(ts: number, now = Date.now() / 1000) {
  const a = new Date(ts * 1000)
  const b = new Date(now * 1000)
  const da = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())
  const db = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())
  const diff = Math.round((da - db) / 86400000)
  if (diff === 0) return "今天"
  if (diff === 1) return "明天"
  if (diff === -1) return "昨天"
  if (diff === 2) return "后天"
  return `${a.getMonth() + 1} 月 ${a.getDate()} 日`
}

/** "2026-10-22 16:17:00" (server local time) -> epoch seconds in the browser's clock */
export function parseServerTime(s: string) {
  return new Date(s.replace(" ", "T")).getTime() / 1000
}
