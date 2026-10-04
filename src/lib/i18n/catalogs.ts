/**
 * Every UI string, per language and namespace. A key is "<namespace>.<path>", e.g.
 * "nav.home" or "picks.empty.title". Adding a namespace: one JSON file per language
 * here, and the same keys in both (src/lib/i18n/i18n.test.ts checks it).
 */
import esAdmin from "@/locales/es/admin.json";
import esAuth from "@/locales/es/auth.json";
import esCommon from "@/locales/es/common.json";
import esErrors from "@/locales/es/errors.json";
import esHome from "@/locales/es/home.json";
import esLive from "@/locales/es/live.json";
import esMarkets from "@/locales/es/markets.json";
import esMatch from "@/locales/es/match.json";
import esMatches from "@/locales/es/matches.json";
import esNav from "@/locales/es/nav.json";
import esOdds from "@/locales/es/odds.json";
import esParlays from "@/locales/es/parlays.json";
import esPicks from "@/locales/es/picks.json";
import esProfile from "@/locales/es/profile.json";
import esSystem from "@/locales/es/system.json";
import esOps from "@/locales/es/ops.json";
import esResearch from "@/locales/es/research.json";
import esAnalytics from "@/locales/es/analytics.json";
import esCatalog from "@/locales/es/catalog.json";
import esCenter from "@/locales/es/center.json";
import esTruth from "@/locales/es/truth.json";
import enAdmin from "@/locales/en/admin.json";
import enAuth from "@/locales/en/auth.json";
import enCommon from "@/locales/en/common.json";
import enErrors from "@/locales/en/errors.json";
import enHome from "@/locales/en/home.json";
import enLive from "@/locales/en/live.json";
import enMarkets from "@/locales/en/markets.json";
import enMatch from "@/locales/en/match.json";
import enMatches from "@/locales/en/matches.json";
import enNav from "@/locales/en/nav.json";
import enOdds from "@/locales/en/odds.json";
import enParlays from "@/locales/en/parlays.json";
import enPicks from "@/locales/en/picks.json";
import enProfile from "@/locales/en/profile.json";
import enSystem from "@/locales/en/system.json";
import enOps from "@/locales/en/ops.json";
import enResearch from "@/locales/en/research.json";
import enAnalytics from "@/locales/en/analytics.json";
import enCatalog from "@/locales/en/catalog.json";
import enCenter from "@/locales/en/center.json";
import enTruth from "@/locales/en/truth.json";

export type Locale = "es" | "en";
export type Catalog = { [key: string]: string | Catalog };

export const CATALOGS: Record<Locale, Catalog> = {
  es: {
    admin: esAdmin,
    auth: esAuth,
    common: esCommon,
    errors: esErrors,
    home: esHome,
    live: esLive,
    markets: esMarkets,
    match: esMatch,
    matches: esMatches,
    nav: esNav,
    odds: esOdds,
    parlays: esParlays,
    picks: esPicks,
    profile: esProfile,
    system: esSystem,
    ops: esOps,
    research: esResearch,
    analytics: esAnalytics,
    catalog: esCatalog,
    center: esCenter,
    truth: esTruth,
  },
  en: {
    admin: enAdmin,
    auth: enAuth,
    common: enCommon,
    errors: enErrors,
    home: enHome,
    live: enLive,
    markets: enMarkets,
    match: enMatch,
    matches: enMatches,
    nav: enNav,
    odds: enOdds,
    parlays: enParlays,
    picks: enPicks,
    profile: enProfile,
    system: enSystem,
    ops: enOps,
    research: enResearch,
    analytics: enAnalytics,
    catalog: enCatalog,
    center: enCenter,
    truth: enTruth,
  },
};
