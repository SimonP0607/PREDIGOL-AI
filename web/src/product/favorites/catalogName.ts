/**
 * A market of a match's catalogue in the reader's words, from the key the catalogue gives it (`code.period.subject`:
 * `corners_over_under.FT.match` → «Más/menos córners»; a team's market says «local» or «visitante», a half its period).
 * Only words the catalogue already translates (`match.catalog.market.*`, `match.catalog.period.*`); a code without one reads
 * as «Otro mercado», never as the provider's key. Pure, no state.
 */
import { t, translateOr } from "@/lib/i18n";

export function catalogKeyName(key: string): string {
  const [code = "", period = "FT", subject = "match"] = key.split(".");
  const name = translateOr(`match.catalog.market.${code}`, t("match.catalog.market.other"));
  const side =
    subject === "home"
      ? ` · ${t("onboarding.follow.catalogSideHome")}`
      : subject === "away"
        ? ` · ${t("onboarding.follow.catalogSideAway")}`
        : "";
  const when =
    period === "FT"
      ? ""
      : ` · ${translateOr(`match.catalog.period.${period}`, t("match.catalog.period.other"))}`;
  return `${name}${side}${when}`;
}
