import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  createRootRouteWithContext,
  useNavigate,
  useRouter,
  useRouterState,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { RefreshCw, ShieldAlert, WifiOff } from "lucide-react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { AuthProvider, useAuth } from "@/lib/auth/AuthProvider";
import { I18nProvider, t } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import { UserShell } from "@/components/layout/UserShell";
import { AdminShell } from "@/components/layout/AdminShell";
import { BrandMark } from "@/components/brand/Brand";
import { applyUpdate, registerServiceWorker, UPDATE_EVENT } from "@/lib/pwa";
import { SecurityStep } from "@/product/auth/SecurityStep";

function NotFoundComponent() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <h1 className="font-display text-6xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">{t("errors.pageNotFound")}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{t("errors.pageNotFoundBody")}</p>
        <a
          href="/home"
          className="mt-6 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {t("auth.goHome")}
        </a>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          {t("errors.pageCrashed")}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{t("errors.pageCrashedBody")}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              void router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t("common.retry")}
          </button>
          <a
            href="/home"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-accent"
          >
            {t("auth.goHome")}
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
      { name: "theme-color", content: "#0d1512" },
      { title: "PrediGol — Football Intelligence" },
      {
        name: "description",
        content: "PrediGol: partidos, en vivo, picks con valor, parlays y las mejores cuotas.",
      },
      { property: "og:title", content: "PrediGol — Football Intelligence" },
      { property: "og:type", content: "website" },
      { name: "robots", content: "noindex, nofollow" },
      // Installed on a phone's home screen (PWA): full screen, its own name and status bar.
      { name: "mobile-web-app-capable", content: "yes" },
      { name: "apple-mobile-web-app-capable", content: "yes" },
      { name: "apple-mobile-web-app-title", content: "PrediGol" },
      { name: "apple-mobile-web-app-status-bar-style", content: "black-translucent" },
    ],
    links: [
      { rel: "stylesheet", href: appCss },
      { rel: "manifest", href: "/manifest.webmanifest" },
      { rel: "icon", href: "/favicon.ico", sizes: "any" },
      { rel: "apple-touch-icon", href: "/apple-touch-icon.png" },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap",
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

/** Logo on the background: what the server renders, and what shows while the session is checked. */
function Splash() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background" aria-busy="true">
      <BrandMark size={72} className="animate-pulse opacity-90" />
    </div>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  // Everything below depends on the browser: the session cookie, the reader's language
  // and time zone. Rendering it only after mount keeps the server's HTML (the splash)
  // and the client's first render identical.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    void registerServiceWorker();
  }, []);
  if (!mounted) return <Splash />;
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Localized>
          <Gate />
          <UpdateToast />
        </Localized>
      </AuthProvider>
    </QueryClientProvider>
  );
}

/** A new version of the app is installed and waiting: the reader decides when to switch (public/sw.js). */
function UpdateToast() {
  const [worker, setWorker] = useState<{ postMessage: (m: unknown) => void } | null>(null);
  useEffect(() => {
    function onReady(event: Event) {
      setWorker((event as CustomEvent<{ postMessage: (m: unknown) => void }>).detail);
    }
    window.addEventListener(UPDATE_EVENT, onReady);
    return () => window.removeEventListener(UPDATE_EVENT, onReady);
  }, []);
  if (!worker) return null;
  return (
    <div
      role="status"
      data-testid="update-toast"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-lg border border-primary/40 bg-card px-4 py-3 text-sm shadow-xl sm:inset-x-auto sm:right-4"
    >
      <span>{t("common.updateReady")}</span>
      <span className="flex shrink-0 gap-2">
        <button
          type="button"
          onClick={() => setWorker(null)}
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
        >
          {t("common.updateLater")}
        </button>
        <button
          type="button"
          onClick={() => applyUpdate(worker)}
          data-testid="update-now"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
        >
          <RefreshCw aria-hidden className="h-3.5 w-3.5" />
          {t("common.updateNow")}
        </button>
      </span>
    </div>
  );
}

function Localized({ children }: { children: ReactNode }) {
  const auth = useAuth();
  setTimeZone(auth.timeZone);
  useEffect(() => {
    document.documentElement.lang = auth.locale;
  }, [auth.locale]);
  return <I18nProvider locale={auth.locale}>{children}</I18nProvider>;
}

function ConnectionProblem({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <BrandMark size={64} />
      <WifiOff aria-hidden className="h-5 w-5 text-warning" />
      <p className="max-w-sm text-sm text-muted-foreground">{t("errors.unreachable")}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
      >
        {t("common.retry")}
      </button>
    </div>
  );
}

function Forbidden() {
  const auth = useAuth();
  return (
    <div
      className="flex min-h-[60vh] flex-col items-center justify-center gap-3 px-6 text-center"
      data-testid="forbidden"
    >
      <ShieldAlert aria-hidden className="h-8 w-8 text-warning" />
      <h1 className="font-display text-xl font-semibold">{t("auth.forbiddenTitle")}</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        {auth.previewAsUser ? t("nav.previewing") : t("auth.forbiddenBody")}
      </p>
      <div className="flex gap-2">
        <a
          href="/home"
          className="rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-elevated"
        >
          {t("auth.goHome")}
        </a>
        {auth.previewAsUser ? (
          <button
            type="button"
            onClick={() => auth.setPreviewAsUser(false)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
          >
            {t("nav.exitPreview")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Who sees what. The server decides access for every request; this decides only where
 * the reader is sent and which shell frames the page.
 */
function Gate() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useRouterState({ select: (s) => s.location });
  const path = location.pathname;
  const onLogin = path === "/login";
  const onAdmin = path === "/admin" || path.startsWith("/admin/");

  useEffect(() => {
    if (auth.status === "anonymous" && !onLogin) {
      const next = `${location.pathname}${location.searchStr ?? ""}`;
      void navigate({
        to: "/login",
        search: { next, expired: auth.sessionExpired ? "1" : undefined } as never,
        replace: true,
      });
    } else if (auth.status === "signed-in" && onLogin) {
      const params = new URLSearchParams(location.searchStr ?? "");
      const next = params.get("next");
      const safe =
        next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login")
          ? next
          : "/home";
      void navigate({ to: safe as never, replace: true });
    }
  }, [auth.status, auth.sessionExpired, onLogin, location.pathname, location.searchStr, navigate]);

  if (auth.status === "loading") return <Splash />;
  if (auth.status === "error") return <ConnectionProblem onRetry={auth.retry} />;
  // The password was right but a step is owed (second factor, setting it up, a new password): that step,
  // whatever the address; the page the reader wanted shows once it is done.
  if (auth.status === "staged") return <SecurityStep />;
  if (auth.status === "anonymous") return onLogin ? <Outlet /> : <Splash />;
  if (onLogin) return <Splash />;

  // A remount on a language or time-zone change re-renders every formatted string.
  const key = `${auth.locale}|${auth.timeZone}`;
  if (onAdmin) {
    return (
      <Fragment key={key}>
        {auth.showAdmin ? (
          <AdminShell>
            <Outlet />
          </AdminShell>
        ) : (
          <UserShell>
            <Forbidden />
          </UserShell>
        )}
      </Fragment>
    );
  }
  return (
    <Fragment key={key}>
      <UserShell>
        <Outlet />
      </UserShell>
    </Fragment>
  );
}
