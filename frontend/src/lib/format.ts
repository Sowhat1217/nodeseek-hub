export const yuan = (v: number | null | undefined, signed = false) => {
  if (v === null || v === undefined) return "—"
  const s = Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("zh-CN") : String(Math.round(v * 10) / 10)
  return (signed && v > 0 ? "+" : v < 0 ? "−" : "") + "¥" + s.replace("-", "")
}

export const compact = (n: number) => (n >= 10000 ? (n / 10000).toFixed(n >= 100000 ? 0 : 1) + "万" : n.toLocaleString("zh-CN"))

export const md = (date: string) => {
  const [, m, d] = date.split("-")
  return `${Number(m)}/${Number(d)}`
}

export const bytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`

/** relative change, as "+12%" / "−3%"; null when there is nothing to compare with */
export function pctChange(cur: number | null, prev: number | null) {
  if (cur === null || prev === null || prev === 0) return null
  return ((cur - prev) / Math.abs(prev)) * 100
}
