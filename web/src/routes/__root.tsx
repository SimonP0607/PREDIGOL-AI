import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  createRootRouteWithContext,
  useNavigate,
  useRouter,
  useRouterState,
  HeadContent,
  Scripts,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { RefreshCw, ShieldAlert, WifiOff } from "lucide-react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { reportError, startObservability } from "../lib/observability";
import { AuthProvider, useAuth } from "@/lib/auth/AuthProvider";
import { I18nProvider, t, translate } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n/catalogs";
import { requestLocale } from "@/lib/i18n/requestLocale";
import { TitleTap } from "@/components/system/TitleTap";
import { setTimeZone } from "@/lib/time";
import { UserShell } from "@/components/layout/UserShell";
import { PublicShell } from "@/components/layout/PublicShell";
import { AdminShell } from "@/components/layout/AdminShell";
import { BrandMark } from "@/components/brand/Brand";
import {
  applyUpdate,
  captureInstallPrompt,
  isStandalone,
  markInstalledOnce,
  registerServiceWorker,
  UPDATE_EVENT,
} from "@/lib/pwa";
import { SecurityStep } from "@/product/auth/SecurityStep";
import { ConsentGate } from "@/product/legal/ConsentGate";
import { isLegalPath } from "@/product/legal/links";
import { isAccountPath } from "@/product/auth/accountPaths";
import { isLimitedPath } from "@/product/membership/membership";
import { LimitedAccess } from "@/product/membership/LimitedAccess";
import { noteLocation, noteNoticeLanding, startSession, track } from "@/lib/track";
import { eventCategory, withoutNoticeMark } from "@/lib/push";
import { markTrouble } from "@/lib/feedback/session";
import { TourProvider } from "@/product/tour/Tour";
import { ReportProblemProvider } from "@/product/support/ReportProblem";

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

// Since the R02 upgrade (router-core 1.171.35) the router types what a boundary catches as `unknown`: a loader may
// throw a Response or any value. Both uses below already take unknown.
function ErrorComponent({ error, reset }: ErrorComponentProps) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
    reportError(error, "root"); // to Sentry, when the server switched it on (plan UX, A2)
    markTrouble(); // and no monthly survey for the rest of the visit (B6)
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

/** The page's title and description in a language: the head the server writes, and the one the browser keeps. */
function headText(locale: Locale): { title: string; description: string } {
  return {
    title: translate("common.meta.title", undefined, locale),
    description: translate("common.meta.description", undefined, locale),
  };
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  // The language the page is served in (plan UX, A1, F08): the server's from Accept-Language, then the reader's.
  loader: () => ({ locale: requestLocale() }),
  head: ({ loaderData }) => {
    const { title, description } = headText(loaderData?.locale ?? "es");
    return {
      meta: [
        { charSet: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
        { name: "theme-color", content: "#0d1512" },
        { title },
        { name: "description", content: description },
        { property: "og:title", content: title },
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
        // The fonts are served from PrediGol, inside styles.css (plan UX, A4): no request to Google.
      ],
    };
  },
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  const data = Route.useLoaderData();
  // The server's language (Accept-Language); the browser sets the reader's once it runs (Localized), so the two
  // may differ at hydration on purpose.
  return (
    <html lang={data.locale} suppressHydrationWarning>
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
    captureInstallPrompt();
    void registerServiceWorker();
    void startObservability();
  }, []);
  if (!mounted) return <Splash />;
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Localized>
          <TourProvider>
            <ReportProblemProvider>
              <Gate />
            </ReportProblemProvider>
          </TourProvider>
          <UpdateToast />
          <TitleTap />
        </Localized>
      </AuthProvider>
    </QueryClientProvider>
  );
}

/**
 * A new version of the app is installed and waiting: the reader decides when to switch (public/sw.js). On a phone or
 * a tablet it floats above the tab bar and the parlay button (plan UX, A1, defect F33: it covered the tab bar); on a
 * desk, bottom left, clear of the parlay button. Its buttons are 44 px tall under a finger.
 */
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
      className="fixed inset-x-4 bottom-[calc(8.5rem+env(safe-area-inset-bottom))] z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-lg border border-primary/40 bg-card px-4 py-3 text-sm shadow-xl short:bottom-[calc(7rem+env(safe-area-inset-bottom))] lg:inset-x-auto lg:bottom-4 lg:left-4"
    >
      <span>{t("common.updateReady")}</span>
      <span className="flex shrink-0 gap-2">
        <button
          type="button"
          onClick={() => setWorker(null)}
          data-testid="update-later"
          className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground pointer-coarse:min-h-11 pointer-coarse:px-3"
        >
          {t("common.updateLater")}
        </button>
        <button
          type="button"
          onClick={() => applyUpdate(worker)}
          data-testid="update-now"
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground pointer-coarse:min-h-11"
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
  const router = useRouter();
  useEffect(() => {
    // The page speaks the reader's language from here on (plan UX, A1, F08): lang at once, and the heads again -
    // the root loader now reads the reader's language (remembered by the auth layer), so every title follows it.
    document.documentElement.lang = auth.locale;
    void router.invalidate();
  }, [auth.locale, router]);
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
  // The legal texts are public (plan UX, A4): anyone reads the terms before having an account.
  const onLegal = isLegalPath(path);
  // Activating an invitation, recovering a password, unlocking (plan UX, A7): public, whatever the session.
  const onAccount = isAccountPath(path);
  // The account's welcome (plan UX, A13): once, after the consents - its own page, whatever the address asked for.
  const onWelcome = path === "/welcome";
  const consentsDone = (auth.user?.consents_due ?? []).length === 0;
  const welcomeOwed =
    auth.status === "signed-in" &&
    consentsDone &&
    Boolean(auth.user?.welcome_due) &&
    !onWelcome &&
    !onLegal &&
    !onAccount &&
    !onAdmin &&
    path !== "/profile";
  // Plan UX, A6: where the reader comes from (match_opened's origin) and the session's start, once per tab.
  useEffect(() => noteLocation(path), [path]);
  const measured = auth.status === "signed-in" && (auth.user?.consents_due ?? []).length === 0;
  useEffect(() => {
    if (!measured) return;
    startSession(auth.locale);
    // Plan UX, A15 (section 35): the first opening of the installed app on this device - the rule that also counts
    // an iPhone, which never fires appinstalled.
    if (isStandalone() && markInstalledOnce()) track("pwa_installed");
  }, [measured, auth.locale]);
  // Plan UX, B7: a notice tapped on the device opened this page (public/sw.js marks it ?notice=<category>) - counted
  // once the reader is in (after signing in, if the session had ended), and then the mark leaves the address.
  useEffect(() => {
    if (!measured) return;
    const params = new URLSearchParams(location.searchStr ?? "");
    if (!params.has("notice")) return;
    const category = eventCategory(params.get("notice"));
    if (category) {
      track("notification_opened", { category });
      noteNoticeLanding();
    }
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${withoutNoticeMark(window.location.search)}${window.location.hash}`,
    );
  }, [measured, location.searchStr]);

  useEffect(() => {
    if (auth.status === "anonymous" && !onLogin && !onLegal && !onAccount) {
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
  }, [
    auth.status,
    auth.sessionExpired,
    onLogin,
    onLegal,
    onAccount,
    location.pathname,
    location.searchStr,
    navigate,
  ]);

  // The welcome is owed: to /welcome, keeping where the reader was going (a link they opened) for after it.
  useEffect(() => {
    if (!welcomeOwed) return;
    const asked = `${location.pathname}${location.searchStr ?? ""}`;
    void navigate({
      to: "/welcome",
      search: (path === "/home" || path === "/" ? {} : { next: asked }) as never,
      replace: true,
    });
  }, [welcomeOwed, location.pathname, location.searchStr, path, navigate]);

  if (auth.status === "loading") return <Splash />;
  if (auth.status === "error") return <ConnectionProblem onRetry={auth.retry} />;
  // The account pages carry their own frame, signed in or not, with a step owed or not.
  if (onAccount) return <Outlet />;
  // The password was right but a step is owed (second factor, setting it up, a new password): that step,
  // whatever the address; the page the reader wanted shows once it is done.
  if (auth.status === "staged") return <SecurityStep />;
  if (auth.status === "anonymous") {
    if (onLegal) {
      return (
        <PublicShell key={auth.locale}>
          <Outlet />
        </PublicShell>
      );
    }
    return onLogin ? <Outlet /> : <Splash />;
  }
  if (onLogin) return <Splash />;

  // A remount on a language or time-zone change re-renders every formatted string.
  const key = `${auth.locale}|${auth.timeZone}`;
  // The current consents are owed (plan UX, A4; the server refuses the product with 403 consent_required): the
  // boxes, whatever the address - except the texts themselves and the profile, where the reader can still take a
  // copy of their data or ask for its deletion without accepting.
  const due = auth.user?.consents_due ?? [];
  if (due.length > 0 && !onLegal && path !== "/profile") {
    return <ConsentGate key={key} due={due} />;
  }
  // The welcome (plan UX, A13): its own frame, like the consents'; the page sends the reader on when nothing is owed.
  if (onWelcome) return <Outlet key={key} />;
  if (welcomeOwed) return <Splash />;
  // The membership has ended or is suspended (plan UX, A8; the server refuses the product with 403
  // membership_expired / membership_suspended): what a limited account can do, on every page but those it still
  // opens - its profile, its saved picks, the help and the legal texts.
  const member = auth.user?.membership;
  if (member?.limited && !onAdmin && !isLimitedPath(path)) {
    return (
      <Fragment key={key}>
        <UserShell>
          <LimitedAccess membership={member} />
        </UserShell>
      </Fragment>
    );
  }
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
