/**
 * Navigation. The product (USER) and the Admin Console (SUPER_ADMIN) are two separate
 * trees: the product never links into /admin, and hiding a link is presentation only -
 * the API refuses every admin route to a USER on its own.
 *
 * The product has five destinations (plan UX, A15, section 36): Inicio, Partidos, Picks, Mis picks and «Más» - on
 * the phone's bottom bar and in the desk's top bar alike. En vivo is a filter of Partidos and its board (/live) stays
 * at its address, under Partidos; Parlays, Cuotas, Transparencia, Ayuda, Perfil, Glosario and Novedades live in «Más».
 * No address changed.
 */
import {
  Activity,
  Banknote,
  BarChart3,
  BookOpen,
  Bookmark,
  BrainCircuit,
  CalendarDays,
  ClipboardList,
  Cpu,
  Database,
  Flag,
  FlaskConical,
  Gauge,
  House,
  Layers,
  LifeBuoy,
  LineChart,
  ListChecks,
  Mail,
  Megaphone,
  Radar,
  ScanSearch,
  ScrollText,
  Settings,
  ShieldCheck,
  Target,
  TrendingUp,
  Trophy,
  UserRound,
  Users,
  Workflow,
  HardDrive,
  Newspaper,
  Shield,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  /** i18n key of the label. */
  label: string;
  icon: LucideIcon;
  exact?: boolean;
  /** Other addresses this destination holds (Partidos holds the live board, /live). */
  also?: readonly string[];
}

/** A destination of the desk's bar: a 40 px pill, 44 px to the finger of a touch laptop. */
export const NAV_PILL =
  "tap-y motion-press relative inline-flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary";

/**
 * The way back at the top of a page («Noche de partido», the system's sheet 5): it says where it goes («Partidos», never
 * «Atrás»), 44 px tall, with a chevron (h-5 w-5) before the word.
 */
export const BACK_LINK =
  "tap-y motion-press relative inline-flex min-h-11 items-center gap-0.5 self-start rounded-chip pr-2 text-sm font-semibold text-foreground hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary";

/** The four addresses of the bar, before «Más». */
export const userNav: NavItem[] = [
  { to: "/home", label: "nav.home", icon: House },
  { to: "/matches", label: "nav.matches", icon: CalendarDays, also: ["/live"] },
  { to: "/picks", label: "nav.picks", icon: Target },
  { to: "/my-picks", label: "nav.myPicks", icon: Bookmark },
];

/**
 * At a wide desk (1280 px and up) these destinations of «Más» are pills of the top bar too (plan maestro UX/UI 2026, sheet
 * S5 and the desk sheets I06, P11, K08: Inicio, Partidos, Picks, Mis picks, Parlays, Cuotas, Noticias and «Más»). Under
 * that width there is no room for them and they stay in «Más», as on the phone. Noticias only while its section is open.
 */
export const DESK_BAR: readonly string[] = ["/parlays", "/odds", "/news"];

/** The switches that shape the bars (GET /auth/me): the unified plan's bars, and the sections they hold. */
export interface NavFlags {
  /** FBI_NAV_V2 (UX-152, decisions D-01 and D-02). */
  v2: boolean;
  /** The Noticias section is open (FBI_NEWS_FEED). */
  news: boolean;
  /** The pages of clubs, national teams and players are open (FBI_PROFILES): «Equipos». */
  profiles: boolean;
}

export const NAV_V1: NavFlags = { v2: false, news: false, profiles: false };

/**
 * The bar's addresses before «Más» (plan maestro unificado, decision D-01): Inicio · Partidos · Noticias · Picks on the
 * phone's bar and at the start of the desk's - «Mis picks» moves to «Más» and to a tab of Picks. Without the switch, or
 * while Noticias is closed, the bar of always.
 */
export function barNav(f: NavFlags = NAV_V1): NavItem[] {
  if (!f.v2 || !f.news) return userNav;
  return [
    { to: "/home", label: "nav.home", icon: House },
    { to: "/matches", label: "nav.matches", icon: CalendarDays, also: ["/live"] },
    { to: "/news", label: "nav.news", icon: Newspaper },
    { to: "/picks", label: "nav.picks", icon: Target },
  ];
}

/** Where a desk pill starts to fit: from 1024 px (lg), 1280 px (xl) or 1600 px (a wide screen, decision D-02). */
export type DeskFrom = "lg" | "xl" | "wide";

export interface DeskExtra {
  item: NavItem;
  from: DeskFrom;
}

/** The pill's own classes for where it fits; under that width it stays in «Más». */
export const DESK_SHOW: Record<DeskFrom, string> = {
  lg: "inline-flex",
  xl: "hidden xl:inline-flex",
  wide: "hidden min-[1600px]:inline-flex",
};

/** And the row of «Más» that the pill replaces, hidden where the pill is shown. */
export const MORE_HIDE: Record<DeskFrom, string> = {
  lg: "lg:hidden",
  xl: "xl:hidden",
  wide: "min-[1600px]:hidden",
};

/**
 * The desk's pills after the bar's four (decision D-02): Equipos from 1024 px while the profiles are open, Mis picks and
 * Parlays from 1280 px, Cuotas from 1600 px; «Más» after them. Without the switch, the bar of always (Parlays, Cuotas and
 * Noticias from 1280 px).
 */
export function deskExtras(f: NavFlags = NAV_V1): DeskExtra[] {
  if (!f.v2 || !f.news)
    return DESK_BAR.map((to) => ({
      item: moreNav.find((m) => m.to === to)!,
      from: "xl" as const,
    })).filter((x) => x.item !== undefined);
  const out: DeskExtra[] = [];
  if (f.profiles)
    out.push({ item: { to: "/teams", label: "nav.teams", icon: Shield }, from: "lg" });
  out.push({ item: { to: "/my-picks", label: "nav.myPicks", icon: Bookmark }, from: "xl" });
  out.push({ item: moreNav.find((m) => m.to === "/parlays")!, from: "xl" });
  out.push({ item: moreNav.find((m) => m.to === "/odds")!, from: "wide" });
  return out;
}

export interface MoreItem extends NavItem {
  /** i18n key of the one line under the label. */
  hint: string;
  testId: string;
  /** Shown only while «Cómo le va a PrediGol» is open to readers (the owner reviews it first; plan UX, A12). */
  transparency?: boolean;
  /** Shown only while the Noticias section is open to readers (FBI_NEWS_FEED; plan maestro UX/UI 2026, decision 2). */
  news?: boolean;
}

/** What «Más» holds, in the plan's order (section 36): Novedades, since B6, after Glosario. */
export const moreNav: MoreItem[] = [
  {
    to: "/parlays",
    label: "nav.parlays",
    hint: "nav.moreHint.parlays",
    icon: Layers,
    testId: "more-parlays",
  },
  {
    to: "/odds",
    label: "nav.odds",
    hint: "nav.moreHint.odds",
    icon: TrendingUp,
    testId: "more-odds",
  },
  {
    to: "/transparency",
    label: "nav.transparency",
    hint: "nav.moreHint.transparency",
    icon: BarChart3,
    testId: "more-transparency",
    transparency: true,
  },
  {
    to: "/news",
    label: "nav.news",
    hint: "nav.moreHint.news",
    icon: Newspaper,
    testId: "more-news",
    news: true,
  },
  {
    to: "/help",
    label: "nav.help",
    hint: "nav.moreHint.help",
    icon: LifeBuoy,
    testId: "more-help",
  },
  {
    to: "/profile",
    label: "nav.profile",
    hint: "nav.moreHint.profile",
    icon: UserRound,
    testId: "more-profile",
  },
  {
    to: "/help/glossary",
    label: "nav.glossary",
    hint: "nav.moreHint.glossary",
    icon: BookOpen,
    testId: "more-glossary",
  },
  {
    to: "/updates",
    label: "nav.updates",
    hint: "nav.moreHint.updates",
    icon: Megaphone,
    testId: "more-updates",
  },
];

/** Novedades: «Más» carries a dot while it holds an entry the reader has not seen (plan UX, B6). */
export const UPDATES_PATH = "/updates";

/** «Mis picks» and «Equipos» as rows of «Más» once the unified plan's bars are on (they left the phone's bar). */
const MY_PICKS_MORE: MoreItem = {
  to: "/my-picks",
  label: "nav.myPicks",
  hint: "nav.moreHint.myPicks",
  icon: Bookmark,
  testId: "more-my-picks",
};
const TEAMS_MORE: MoreItem = {
  to: "/teams",
  label: "nav.teams",
  hint: "nav.moreHint.teams",
  icon: Shield,
  testId: "more-teams",
};

/** The items of «Más» this reader sees. */
export function moreItems(
  showTransparency: boolean,
  showNews = false,
  f: NavFlags = NAV_V1,
): MoreItem[] {
  const base = moreNav.filter(
    (item) => (!item.transparency || showTransparency) && (!item.news || showNews),
  );
  if (!f.v2 || !f.news) return base;
  // Noticias is in the bar now; Mis picks (and Equipos, while the profiles are open) come into «Más».
  return [
    MY_PICKS_MORE,
    ...(f.profiles ? [TEAMS_MORE] : []),
    ...base.filter((item) => item.to !== "/news"),
  ];
}

/**
 * «Evaluación privada · no visible para usuarios» (kit of the maquetas): the owner's own rows at the foot of «Más» - only
 * with the console's role, while the unified plan's bars are on. Each address is a console route the API keeps for the
 * owner alone. The tracking and line-up alert views join it as they are built (UX-167, UX-169).
 */
export function privateItems(admin: boolean, f: NavFlags = NAV_V1): MoreItem[] {
  if (!admin || !f.v2) return [];
  return [
    {
      to: "/admin/intelligence",
      label: "nav.private.console",
      hint: "nav.private.consoleHint",
      icon: BrainCircuit,
      testId: "more-private-console",
    },
  ];
}

/** The class that hides a row of «Más» where the desk's bar shows it as a pill (none: always a row). */
export function moreHide(to: string, f: NavFlags = NAV_V1): string | undefined {
  const extra = deskExtras(f).find((x) => x.item.to === to);
  return extra ? MORE_HIDE[extra.from] : undefined;
}

export const profileNav: NavItem = { to: "/profile", label: "nav.profile", icon: UserRound };

/** The console's first screen, above the groups (plan maestro UX/UI 2026, decision 12). */
export const adminHome: NavItem = {
  to: "/admin/overview",
  label: "admin.nav.overview",
  icon: Gauge,
};

export interface AdminNavGroup {
  /** Stable: the key the browser remembers a folded group by. */
  key: "customers" | "market" | "intelligence" | "football" | "system";
  label: string;
  items: NavItem[];
}

/**
 * The console's menu in five groups (decision 12): the same destinations as before, less «Clientes» (a view of «Usuarios», AP-A03) - «Resumen» above them - with
 * the same routes and the same permissions. Only where each one is listed changes.
 */
export const adminNav: AdminNavGroup[] = [
  {
    key: "customers",
    label: "admin.groups.customers",
    items: [
      { to: "/admin/payments", label: "admin.nav.payments", icon: Banknote },
      { to: "/admin/support", label: "admin.nav.support", icon: LifeBuoy },
      { to: "/admin/announcements", label: "admin.nav.announcements", icon: Megaphone },
      { to: "/admin/messages", label: "admin.nav.messages", icon: Mail },
      { to: "/admin/users", label: "admin.nav.users", icon: UserRound },
      { to: "/admin/product", label: "admin.nav.product", icon: BarChart3 },
    ],
  },
  {
    key: "market",
    label: "admin.groups.market",
    items: [
      { to: "/admin/picks", label: "admin.nav.picks", icon: ListChecks },
      { to: "/admin/performance", label: "admin.nav.performance", icon: LineChart },
      { to: "/admin/odds", label: "admin.nav.odds", icon: TrendingUp },
    ],
  },
  {
    key: "intelligence",
    label: "admin.groups.intelligence",
    items: [
      { to: "/admin/models", label: "admin.nav.models", icon: Cpu },
      { to: "/admin/backtesting", label: "admin.nav.backtesting", icon: FlaskConical },
      { to: "/admin/analytics", label: "admin.nav.analytics", icon: BarChart3 },
      { to: "/admin/operation", label: "admin.nav.operation", icon: Radar },
      { to: "/admin/learning", label: "admin.nav.learning", icon: BrainCircuit },
    ],
  },
  {
    key: "football",
    label: "admin.groups.football",
    items: [
      { to: "/admin/competitions", label: "admin.nav.competitions", icon: Trophy },
      { to: "/admin/teams", label: "admin.nav.teams", icon: ShieldCheck },
      { to: "/admin/players", label: "admin.nav.players", icon: Users },
      { to: "/admin/referees", label: "admin.nav.referees", icon: Flag },
      { to: "/admin/rankings", label: "admin.nav.rankings", icon: Activity },
    ],
  },
  {
    key: "system",
    label: "admin.groups.system",
    items: [
      { to: "/admin/system", label: "admin.nav.system", icon: ClipboardList },
      { to: "/admin/data-truth", label: "admin.nav.dataTruth", icon: ScanSearch },
      { to: "/admin/data-quality", label: "admin.nav.dataQuality", icon: Database },
      { to: "/admin/storage", label: "admin.nav.storage", icon: HardDrive },
      { to: "/admin/migration", label: "admin.nav.migration", icon: Workflow },
      { to: "/admin/audit", label: "admin.nav.audit", icon: ScrollText },
      { to: "/admin/settings", label: "admin.nav.settings", icon: Settings },
    ],
  },
];

/** Every destination of the console's menu, «Resumen» first: 27. */
export const adminDestinations: NavItem[] = [adminHome, ...adminNav.flatMap((g) => g.items)];

const ADMIN_NAV_KEY = "predigol.admin.nav.folded";

/** The groups this browser folded, by key. Storage can be missing or refuse: then nothing is folded. */
export function readFoldedAdminGroups(store: Pick<Storage, "getItem"> | null): Set<string> {
  try {
    const raw = store?.getItem(ADMIN_NAV_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    const known = new Set<string>(adminNav.map((g) => g.key));
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((k): k is string => typeof k === "string" && known.has(k))
        : [],
    );
  } catch {
    return new Set();
  }
}

export function writeFoldedAdminGroups(
  store: Pick<Storage, "setItem"> | null,
  folded: ReadonlySet<string>,
): void {
  try {
    store?.setItem(ADMIN_NAV_KEY, JSON.stringify([...folded].sort()));
  } catch {
    // a browser that keeps nothing still folds and unfolds: it just forgets on the next visit
  }
}

/** The group a path belongs to: it is shown open whatever the browser remembers, so the current page is never hidden. */
export function adminGroupOf(pathname: string): AdminNavGroup["key"] | null {
  return adminNav.find((g) => g.items.some((i) => isActive(pathname, i.to, i.exact)))?.key ?? null;
}

export function isActive(pathname: string, to: string, exact = false): boolean {
  return exact ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
}

/** Whether a destination of the bar holds this page (its own address or one it holds, like Partidos' /live). */
export function holds(item: Pick<NavItem, "to" | "also" | "exact">, pathname: string): boolean {
  return [item.to, ...(item.also ?? [])].some((to) => isActive(pathname, to, item.exact));
}

/** The item of «Más» this page belongs to - the longest address that holds it (/help/glossary is Glosario, not Ayuda). */
export function currentMore(
  pathname: string,
  items: readonly MoreItem[] = moreNav,
): MoreItem | null {
  let best: MoreItem | null = null;
  for (const item of items) {
    if (isActive(pathname, item.to) && (!best || item.to.length > best.to.length)) best = item;
  }
  return best;
}

/** Which of the five destinations holds this page: one of the bar's four addresses, «Más», or none (a legal text). */
export function destinationOf(pathname: string, f: NavFlags = NAV_V1): string | "more" | null {
  const item = barNav(f).find((i) => holds(i, pathname));
  if (item) return item.to;
  return currentMore(pathname, moreItems(true, true, f)) ? "more" : null;
}
