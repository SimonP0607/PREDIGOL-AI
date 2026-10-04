/**
 * Navigation. The product (USER) and the Admin Console (SUPER_ADMIN) are two separate
 * trees: the product never links into /admin, and hiding a link is presentation only -
 * the API refuses every admin route to a USER on its own.
 */
import {
  Activity,
  BarChart3,
  Bookmark,
  Bot,
  CalendarDays,
  ClipboardList,
  Cpu,
  Database,
  FlaskConical,
  Gauge,
  House,
  Layers,
  LineChart,
  ListChecks,
  Radio,
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
}

export const userNav: NavItem[] = [
  { to: "/home", label: "nav.home", icon: House },
  { to: "/matches", label: "nav.matches", icon: CalendarDays },
  { to: "/live", label: "nav.live", icon: Radio },
  { to: "/picks", label: "nav.picks", icon: Target },
  { to: "/parlays", label: "nav.parlays", icon: Layers },
  { to: "/odds", label: "nav.odds", icon: TrendingUp },
  { to: "/my-picks", label: "nav.myPicks", icon: Bookmark },
];

export const profileNav: NavItem = { to: "/profile", label: "nav.profile", icon: UserRound };

export const adminNav: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "admin.groups.operations",
    items: [
      { to: "/admin/overview", label: "admin.nav.overview", icon: Gauge },
      { to: "/admin/picks", label: "admin.nav.picks", icon: ListChecks },
      { to: "/admin/performance", label: "admin.nav.performance", icon: LineChart },
      { to: "/admin/odds", label: "admin.nav.odds", icon: TrendingUp },
    ],
  },
  {
    label: "admin.groups.intelligence",
    items: [
      { to: "/admin/models", label: "admin.nav.models", icon: Cpu },
      { to: "/admin/backtesting", label: "admin.nav.backtesting", icon: FlaskConical },
      { to: "/admin/analytics", label: "admin.nav.analytics", icon: BarChart3 },
      { to: "/admin/ai-analyst", label: "admin.nav.aiAnalyst", icon: Bot },
    ],
  },
  {
    label: "admin.groups.football",
    items: [
      { to: "/admin/competitions", label: "admin.nav.competitions", icon: Trophy },
      { to: "/admin/teams", label: "admin.nav.teams", icon: ShieldCheck },
      { to: "/admin/players", label: "admin.nav.players", icon: Users },
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
      { to: "/admin/audit", label: "admin.nav.audit", icon: ScrollText },
      { to: "/admin/settings", label: "admin.nav.settings", icon: Settings },
    ],
  },
];

export function isActive(pathname: string, to: string, exact = false): boolean {
  return exact ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
}
