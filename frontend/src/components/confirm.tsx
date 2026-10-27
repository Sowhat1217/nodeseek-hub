import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

interface Ask {
  title: string
  description?: string
  action: string
  /** default: destructive (red); "default" for harmless actions like logging out */
  variant?: "destructive" | "default"
}

const Ctx = createContext<(a: Ask) => Promise<boolean>>(async () => false)

/** Promise-based confirmation: `if (await confirm({...})) ...` */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [ask, setAsk] = useState<Ask | null>(null)
  const resolver = useRef<(v: boolean) => void>(() => {})

  const confirm = useCallback((a: Ask) => {
    setAsk(a)
    return new Promise<boolean>((res) => (resolver.current = res))
  }, [])

  const close = (v: boolean) => {
    resolver.current(v)
    setAsk(null)
  }

  return (
    <Ctx.Provider value={confirm}>
      {children}
      <AlertDialog open={!!ask} onOpenChange={(o) => !o && close(false)}>
        <AlertDialogContent className="bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle>{ask?.title}</AlertDialogTitle>
            {ask?.description && <AlertDialogDescription>{ask.description}</AlertDialogDescription>}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => close(false)}>取消</AlertDialogCancel>
            <AlertDialogAction variant={ask?.variant ?? "destructive"} onClick={() => close(true)}>
              {ask?.action}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Ctx.Provider>
  )
}

export const useConfirm = () => useContext(Ctx)
