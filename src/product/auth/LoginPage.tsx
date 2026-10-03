import { useState, type FormEvent } from "react";
import { Eye, EyeOff, Loader2, LogIn } from "lucide-react";
import { BrandCrest } from "@/components/brand/Brand";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LiveApiError } from "@/lib/api/v1/client";
import { t, translateOr } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function loginError(error: unknown, retryAfter: number | null): string {
  if (error instanceof LiveApiError) {
    if (error.status === 0) return t("errors.unreachable");
    if (error.code === "too_many_attempts") {
      return t("errors.code.too_many_attempts", { seconds: retryAfter ?? 60 });
    }
    return translateOr(`errors.code.${error.code}`, t("errors.generic"));
  }
  return t("errors.generic");
}

export function LoginPage({ expired }: { expired: boolean }) {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await auth.signIn(email, password);
    } catch (err) {
      setError(loginError(err, null));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pitch-glow relative flex min-h-screen flex-col bg-background">
      <div className="flex justify-end p-4">
        <LanguageSwitch />
      </div>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm">
          <div className="flex flex-col items-center text-center">
            <BrandCrest size={152} />
            <h1 className="mt-4 font-display text-2xl font-bold tracking-tight">
              {t("auth.title")}
            </h1>
            <p className="mt-1.5 text-sm text-muted-foreground">{t("auth.subtitle")}</p>
          </div>

          <form
            onSubmit={(e) => void submit(e)}
            className="mt-6 space-y-4 rounded-xl border border-border bg-card/90 p-5 shadow-xl backdrop-blur"
            noValidate
          >
            {expired && !error ? (
              <p
                role="status"
                className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-xs text-warning"
              >
                {t("auth.sessionExpired")}
              </p>
            ) : null}
            {error ? (
              <p
                role="alert"
                data-testid="login-error"
                className="rounded-md border border-negative/40 bg-negative-soft px-3 py-2 text-xs text-negative"
              >
                {error}
              </p>
            ) : null}
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">{t("auth.email")}</span>
              <input
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("auth.password")}
              </span>
              <span className="relative mt-1 block">
                <input
                  type={show ? "text" : "password"}
                  name="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3 pr-10 text-sm focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground hover:text-foreground"
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </span>
            </label>
            <button
              type="submit"
              disabled={busy || !email || !password}
              data-testid="login-submit"
              className={cn(
                "flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90",
                (busy || !email || !password) && "cursor-not-allowed opacity-60",
              )}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
              {busy ? t("auth.submitting") : t("auth.submit")}
            </button>
          </form>
          <p className="mt-4 text-center text-caption text-subtle-foreground">
            {t("auth.privateNote")}
          </p>
          <p className="mt-6 text-center text-caption text-subtle-foreground">
            {t("common.disclaimer")}
          </p>
        </div>
      </main>
    </div>
  );
}
