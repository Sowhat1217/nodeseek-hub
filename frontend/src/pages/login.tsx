import { useState, type FormEvent } from "react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { LogoMark } from "@/components/logo"

export default function LoginPage({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!password) return setError("请输入密码")
    setBusy(true)
    setError("")
    try {
      await api.post("/login", { password })
      onDone()
    } catch (err) {
      setError((err as Error).message === "密码错误" ? "密码不对，再试一次" : (err as Error).message)
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
      <div className="flex w-full max-w-sm flex-col gap-6 animate-in fade-in-0 slide-in-from-bottom-2 duration-500">
        <div className="flex items-center gap-2 self-center font-medium">
          <LogoMark className="size-6" />
          NS 聚合
        </div>
        <Card>
          <CardHeader className="text-center">
            <CardTitle className="text-xl">欢迎回来</CardTitle>
            <CardDescription>输入面板密码继续</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} noValidate>
              <FieldGroup>
                <Field data-invalid={!!error}>
                  <FieldLabel htmlFor="password">密码</FieldLabel>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    autoFocus
                    value={password}
                    aria-invalid={!!error}
                    onChange={(e) => {
                      setPassword(e.target.value)
                      setError("")
                    }}
                  />
                  {error && <FieldError>{error}</FieldError>}
                </Field>
                <Button type="submit" className="w-full" disabled={busy}>
                  {busy && <Spinner />}
                  登录
                </Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
