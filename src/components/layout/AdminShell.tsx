import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { ArrowLeft, Eye, Menu, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { BrandMark } from "@/components/brand/Brand";
import { adminNav, isActive } from "./nav";
import { AccountMenu, LanguageSwitch, PreviewBanner } from "./HeaderControls";
import { useQuery } from "@tanstack/react-query";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { DataSourcesProvider, PageDataModeBadge } from "@/components/system/DataSources";
import { DATA_MODE, LIVE_ENABLED } from "@/lib/api/mode";
import { live } from "@/lib/api/v1/queries";
import { formatTime, zoneAbbrev } from "@/lib/time";
import {
  CommandPalette,
  destinationFor,
  searchEmpty,
  useEntitySearch,
} from "@/components/system/CommandPalette";

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <div className="flex h-full flex-col">
      <Link
        to="/admin/overview"
        onClick={onNavigate}
        className="flex items-center gap-2.5 border-b border-sidebar-border px-4 py-3.5"
      >
        <BrandMark size={32} />
        <div className="min-w-0">
          <div className="truncate font-display text-sm font-bold">
            Predi<span className="text-gold">Gol</span>
          </div>
          <div className="text-caption text-subtle-foreground">{t("admin.consoleTitle")}</div>
        </div>
      </Link>

      <nav aria-label={t("nav.adminNavigation")} className="flex-1 overflow-y-auto px-2 py-3">
        {adminNav.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1.5 text-label text-subtle-foreground">{t(group.label)}</div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(pathname, item.to, item.exact);
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      onClick={onNavigate}
                      data-testid={`admin-nav-${item.to.split("/").pop() ?? ""}`}
                      className={cn(
                        "group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      )}
                    >
                      <Icon
                        aria-hidden
                        className={cn(
                          "h-3.5 w-3.5",
                          active ? "text-primary" : "text-subtle-foreground",
                        )}
                      />
                      {t(item.label)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="space-y-2 border-t border-sidebar-border px-3 py-3">
        <Link
          to="/home"
          onClick={onNavigate}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {t("nav.backToApp")}
        </Link>
        <div className="flex items-center justify-between px-2">
          <span className="numeric text-caption text-subtle-foreground">local / {DATA_MODE}</span>
          <StatusBadge tone="brand">{t("admin.shell.shadow")}</StatusBadge>
        </div>
      </div>
    </div>
  );
}

function GlobalSearch({ onOpenPalette }: { onOpenPalette: () => void }) {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const hits = useEntitySearch(term, 6);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={box} className="relative hidden min-w-0 flex-1 md:block md:max-w-md">
      <label className="relative flex items-center">
        <span className="sr-only">{t("admin.shell.searchLabel")}</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-subtle-foreground"
        />
        <input
          type="search"
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
            if (e.key === "Enter" && hits[0]) {
              const hit = hits[0];
              setOpen(false);
              setTerm("");
              if (hit.fixtureId && destinationFor(hit) === "/matches/$fixtureId") {
                void navigate({ to: "/matches/$fixtureId", params: { fixtureId: hit.fixtureId } });
              } else {
                void navigate({ to: destinationFor(hit) });
              }
            }
          }}
          placeholder={t("common.searchPlaceholder")}
          className="h-8 w-full rounded-md border border-border bg-card pl-8 pr-16 text-sm placeholder:text-subtle-foreground focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <button
          type="button"
          onClick={onOpenPalette}
          aria-label={t("admin.shell.openPalette")}
          className="numeric absolute right-1.5 rounded border border-border px-1 py-0.5 text-caption text-subtle-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          ⌘K
        </button>
      </label>

      {open && term.trim() ? (
        <div className="absolute left-0 right-0 top-10 z-40 overflow-hidden rounded-md border border-border bg-card shadow-lg">
          {hits.length === 0 ? (
            <p className="px-3 py-3 text-xs text-subtle-foreground">{searchEmpty()}</p>
          ) : (
            <ul>
              {hits.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      setTerm("");
                      if (h.fixtureId && destinationFor(h) === "/matches/$fixtureId") {
                        void navigate({
                          to: "/matches/$fixtureId",
                          params: { fixtureId: h.fixtureId },
                        });
                      } else {
                        void navigate({ to: destinationFor(h) });
                      }
                    }}
                    className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left text-xs hover:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <span className="truncate">{h.label}</span>
                    <span className="shrink-0 text-caption text-subtle-foreground">
                      {h.sublabel}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * The newest payload the system has stored. Shell chrome, not page content:
 * it deliberately uses a plain query so it does not mark every page as live.
 */
function LastSync() {
  const q = useQuery(live.overview);
  const at = q.data?.data.freshness.last_payload_at ?? null;
  const worker = q.data?.data.worker.alive;
  const tone = q.isError
    ? "bg-negative"
    : worker === false
      ? "bg-negative"
      : at
        ? "bg-positive"
        : "bg-subtle-foreground";
  const label = q.isError
    ? t("admin.shell.apiUnreachable")
    : at
      ? t("admin.shell.lastPayload", { time: `${formatTime(at)} ${zoneAbbrev(at)}` })
      : q.isLoading
        ? t("admin.shell.checking")
        : t("admin.shell.noPayload");
  return (
    <span
      className="hidden items-center gap-1.5 text-caption text-muted-foreground lg:flex"
      title={worker === false ? t("admin.shell.workerDownHelp") : undefined}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", tone)} />
      <span className="numeric">{label}</span>
      {worker === false ? (
        <span className="text-negative">· {t("admin.shell.workerDown")}</span>
      ) : null}
    </span>
  );
}

function Topbar({
  onOpenMenu,
  onOpenPalette,
}: {
  onOpenMenu: () => void;
  onOpenPalette: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur">
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label={t("common.openMenu")}
        className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring lg:hidden"
      >
        <Menu className="h-4 w-4" />
      </button>

      <GlobalSearch onOpenPalette={onOpenPalette} />

      <div className="ml-auto flex min-w-0 shrink-0 items-center gap-2 sm:gap-3">
        <PageDataModeBadge />
        <span className="hidden xl:inline-flex">
          <StatusBadge tone="warning">{t("admin.shell.researchMode")}</StatusBadge>
        </span>
        {LIVE_ENABLED ? <LastSync /> : null}
        <button
          type="button"
          onClick={onOpenPalette}
          aria-label={t("common.search")}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring md:hidden"
        >
          <Search className="h-4 w-4" />
        </button>
        <PreviewButton />
        <LanguageSwitch />
        <AccountMenu />
      </div>
    </header>
  );
}

function PreviewButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  if (!auth.isSuperAdmin) return null;
  return (
    <button
      type="button"
      data-testid="preview-as-user"
      onClick={() => {
        auth.setPreviewAsUser(true);
        void navigate({ to: "/home" });
      }}
      className="hidden items-center gap-1.5 rounded-md border border-gold/45 px-2 py-1 text-xs font-semibold text-gold hover:bg-gold-soft sm:flex"
    >
      <Eye aria-hidden className="h-3.5 w-3.5" />
      {t("nav.previewAsUser")}
    </button>
  );
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  return (
    <DataSourcesProvider>
      <div className="min-h-screen bg-background">
        <PreviewBanner />
        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
        <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-sidebar-border bg-sidebar lg:block">
          <SidebarContent />
        </aside>

        {open ? (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div
              className="absolute inset-0 bg-background/80"
              onClick={() => setOpen(false)}
              aria-hidden
            />
            <div className="absolute inset-y-0 left-0 w-64 border-r border-sidebar-border bg-sidebar">
              <button
                type="button"
                aria-label={t("common.closeMenu")}
                onClick={() => setOpen(false)}
                className="absolute right-2 top-3 rounded-md p-1.5 text-muted-foreground"
              >
                <X className="h-4 w-4" />
              </button>
              <SidebarContent onNavigate={() => setOpen(false)} />
            </div>
          </div>
        ) : null}

        <div className="lg:pl-60">
          <Topbar onOpenMenu={() => setOpen(true)} onOpenPalette={() => setPaletteOpen(true)} />
          <main className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">{children}</main>
        </div>
      </div>
    </DataSourcesProvider>
  );
}
