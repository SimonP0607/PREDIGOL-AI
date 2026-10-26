/**
 * Navigation. The product (USER) and the Admin Console (SUPER_ADMIN) are two separate
 * trees: the product never links into /admin, and hiding a link is presentation only -
 * the API refuses every admin route to a USER on its own.
 *
 * The product has five destinations (plan UX, A15, section 36): Inicio, Partidos, Picks, Mis picks and «Más» - on
 * the phone's bottom bar and in the desk's top bar alike. En vivo is a filter of Partidos and its board (/live) stays
 * at its address, under Partidos; Parlays, Cuotas, Transparencia, Ayuda, Perfil and Glosario live in «Más». No
 * address changed.
 */
import {
  Activity,
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

/** The four addresses of the bar, before «Más». */
export const userNav: NavItem[] = [
  { to: "/home", label: "nav.home", icon: House },
  { to: "/matches", label: "nav.matches", icon: CalendarDays, also: ["/live"] },
  { to: "/picks", label: "nav.picks", icon: Target },
  { to: "/my-picks", label: "nav.myPicks", icon: Bookmark },
];

export interface MoreItem extends NavItem {
  /** i18n key of the one line under the label. */
  hint: string;
  testId: string;
  /** Shown only while «Cómo le va a PrediGol» is open to readers (the owner reviews it first; plan UX, A12). */
  transparency?: boolean;
}

/** What «Más» holds, in the plan's order (section 36). Novedades joins with B6. */
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
];

/** The items of «Más» this reader sees. */
export function moreItems(showTransparency: boolean): MoreItem[] {
  return moreNav.filter((item) => !item.transparency || showTransparency);
}

export const profileNav: NavItem = { to: "/profile", label: "nav.profile", icon: UserRound };

export const adminNav: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "admin.groups.operations",
    items: [
      { to: "/admin/overview", label: "admin.nav.overview", icon: Gauge },
      { to: "/admin/picks", label: "admin.nav.picks", icon: ListChecks },
      { to: "/admin/performance", label: "admin.nav.performance", icon: LineChart },
      { to: "/admin/odds", label: "admin.nav.odds", icon: TrendingUp },
      { to: "/admin/support", label: "admin.nav.support", icon: LifeBuoy },
    ],
  },
  {
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
    label: "admin.groups.system",
    items: [
      { to: "/admin/data-truth", label: "admin.nav.dataTruth", icon: ScanSearch },
      { to: "/admin/data-quality", label: "admin.nav.dataQuality", icon: Database },
      { to: "/admin/system", label: "admin.nav.system", icon: ClipboardList },
      { to: "/admin/migration", label: "admin.nav.migration", icon: Workflow },
      { to: "/admin/users", label: "admin.nav.users", icon: UserRound },
      { to: "/admin/messages", label: "admin.nav.messages", icon: Mail },
      { to: "/admin/product", label: "admin.nav.product", icon: BarChart3 },
      { to: "/admin/audit", label: "admin.nav.audit", icon: ScrollText },
      { to: "/admin/settings", label: "admin.nav.settings", icon: Settings },
    ],
  },
];

export function isActive(pathname: string, to: string, exact = false): boolean {
  return exact ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
}

/** Whether a destination of the bar holds this page (its own address or one it holds, like Partidos' /live). */
export function holds(item: NavItem, pathname: string): boolean {
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
export function destinationOf(pathname: string): string | "more" | null {
  const item = userNav.find((i) => holds(i, pathname));
  if (item) return item.to;
  return currentMore(pathname) ? "more" : null;
}
