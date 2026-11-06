import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, Loader2, LogIn, Mail } from "lucide-react";
import { BrandCrest } from "@/components/brand/Brand";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { Disclaimer } from "@/components/system/Disclaimer";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { t, translateOr } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { AnnouncementBanner } from "@/product/announcements/AnnouncementBanner";
import { LoginContact } from "@/product/support/LoginContact";
import { tooManyAttempts } from "./wait";

/** The refusal in the reader's words; a lock says the real wait, in minutes (plan UX, A1, defect F01). */
function loginError(error: unknown): string {
  if (error instanceof LiveApiError) {
    if (error.status === 0) return t("errors.unreachable");
    if (error.code === "too_many_attempts") return tooManyAttempts(error.retryAfter);
    return translateOr(`errors.code.${error.code}`, t("errors.generic"));
  }
  return t("errors.generic");
}

export function LoginPage({ expired }: { expired: boolean }) {
  const auth = useAuth();
  // Recovery and unlocking by e-mail (plan UX, A7) are offered only while they work (FBI_SELF_SERVICE).
  const options = useQuery({
    queryKey: ["auth", "options"],
    queryFn: v1.accountOptions,
    staleTime: 60_000,
  });
  const selfService = options.data?.self_service === true;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [unlock, setUnlock] = useState<"idle" | "busy" | "sent" | "failed">("idle");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await auth.signIn(email, password);
    } catch (err) {
      setError(loginError(err));
      setLocked(err instanceof LiveApiError && err.code === "too_many_attempts");
      setUnlock("idle");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  async function askUnlock() {
    setUnlock("busy");
    try {
      await v1.requestUnlock(email.trim());
      setUnlock("sent");
    } catch {
      setUnlock("failed");
    }
  }

  return (
    <div className="pitch-glow relative flex min-h-screen flex-col bg-background">
      <div className="flex justify-end p-4">
        <LanguageSwitch />
      </div>
      <AnnouncementBanner />
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
            {locked && selfService && email.trim() ? (
              unlock === "sent" ? (
                <p
                  role="status"
                  data-testid="unlock-sent"
                  className="rounded-md border border-positive/40 bg-positive-soft px-3 py-2 text-xs"
                >
                  {t("auth.account.unlockSent")}
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() => void askUnlock()}
                  disabled={unlock === "busy"}
                  data-testid="ask-unlock"
                  className="tap-y relative flex w-full items-center justify-center gap-2 rounded-md border border-border-strong px-3 py-2 text-xs font-medium hover:bg-elevated"
                >
                  {unlock === "busy" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Mail className="h-3.5 w-3.5" />
                  )}
                  {t("auth.account.askUnlock")}
                </button>
              )
            ) : null}
            {unlock === "failed" ? (
              <p role="alert" data-testid="unlock-failed" className="text-xs text-negative">
                {t("errors.generic")}
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
                className="mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-11"
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
                  className="h-10 w-full rounded-md border border-input bg-background px-3 pr-10 text-base focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-11 pointer-coarse:pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShow((v) => !v)}
                  aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground hover:text-foreground pointer-coarse:w-11"
                >
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </span>
            </label>
            {selfService ? (
              <a
                href="/forgot-password"
                data-testid="forgot-link"
                className="tap-y relative block text-right text-xs text-primary underline-offset-2 hover:underline"
              >
                {t("auth.account.forgotLink")}
              </a>
            ) : null}
            <button
              type="submit"
              disabled={busy || !email || !password}
              data-testid="login-submit"
              className={cn(
                "flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 pointer-coarse:h-11",
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
          <LoginContact />
          <Disclaimer className="mt-6 text-center text-caption text-subtle-foreground" />
        </div>
      </main>
    </div>
  );
}
