/**
 * The sentence of a reason the server chose for a match on Inicio (plan de Inicio, 3.1b): the API sends a code and the values
 * (``HomeReason``) and the words are here, in the reader's language. A reason this client does not know, or one missing a value
 * its sentence needs, says nothing: no line is better than a wrong one.
 */
import { hasKey, t } from "@/lib/i18n";
import type { HomeReason } from "@/lib/api/v1/types_product";

type Params = HomeReason["params"];

function text(p: Params, key: string): string | null {
  const v = p[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

function int(p: Params, key: string): number | null {
  const v = p[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** «Blues pelea por no descender», or null for a pressure the templates do not know. */
function pressureText(team: string | null, pressure: string | null): string | null {
  const key = `home.reason.pressure.${pressure ?? ""}`;
  return team && pressure && hasKey(key) ? t(key, { team }) : null;
}

export function reasonText(reason: HomeReason): string | null {
  const p = reason.params;
  switch (reason.code) {
    case "final":
      return t("home.reason.final");
    case "tie": {
      const home = text(p, "home");
      const away = text(p, "away");
      const h = int(p, "agg_home");
      const a = int(p, "agg_away");
      if (home === null || away === null || h === null || a === null) return null;
      if (h === a) return t("home.reason.tieLevel", { goals: h });
      const homeLeads = h > a;
      return t("home.reason.tieAhead", {
        team: homeLeads ? home : away,
        lead: Math.max(h, a),
        trail: Math.min(h, a),
      });
    }
    case "first_leg": {
      const home = text(p, "home");
      const away = text(p, "away");
      const h = int(p, "first_home");
      const a = int(p, "first_away");
      if (home === null || away === null || h === null || a === null) return null;
      return t("home.reason.firstLeg", { home, away, firstHome: h, firstAway: a });
    }
    case "stakes": {
      const first = pressureText(text(p, "team"), text(p, "pressure"));
      if (first === null) return null;
      const state = text(p, "state");
      if (state !== null) {
        // In play: what the side fights for and how it is going.
        const key = `home.reason.state.${state}`;
        return hasKey(key) ? `${first} ${t(key)}.` : `${first}.`;
      }
      const other = pressureText(text(p, "other_team"), text(p, "other_pressure"));
      return other === null ? `${first}.` : `${t("home.reason.both", { first, second: other })}.`;
    }
    case "comeback": {
      const team = text(p, "team");
      const down = int(p, "down_by");
      const state = text(p, "state");
      if (team === null || down === null || (state !== "level" && state !== "ahead")) return null;
      return t(state === "level" ? "home.reason.comebackLevel" : "home.reason.comebackAhead", {
        team,
        count: down,
      });
    }
    default:
      return null;
  }
}
