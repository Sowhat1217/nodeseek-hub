import { useEffect, useSyncExternalStore } from "react"

export type Theme = "light" | "dark" | "system"

const listeners = new Set<() => void>()
const media = window.matchMedia("(prefers-color-scheme: dark)")

function read(): Theme {
  try {
    const v = localStorage.getItem("theme")
    return v === "light" || v === "dark" ? v : "system"
  } catch {
    return "system"
  }
}

let current: Theme = read()

function apply() {
  const dark = current === "dark" || (current === "system" && media.matches)
  document.documentElement.classList.toggle("dark", dark)
  listeners.forEach((l) => l())
}

media.addEventListener("change", apply)

export function setTheme(t: Theme) {
  current = t
  try {
    localStorage.setItem("theme", t)
  } catch {
    /* storage unavailable: theme still applies for this visit */
  }
  apply()
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => current)
  const resolved = useSyncExternalStore(subscribe, () =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  ) as "light" | "dark"
  useEffect(() => apply(), [])
  return { theme, resolved, setTheme }
}
