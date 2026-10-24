/**
 * What the Intelligence page used to print as raw JSON or as a bare code, said in words (plan F13: "quitar JSON crudo y códigos
 * sin traducir de Intelligence"): the parameters of a calibrator, the criteria fixed in advance, the first leg of a tie, and the
 * codes of a post-mortem and of an outcome.
 *
 * Nothing here ever prints JSON. A key or a code nobody has named yet is shown as it comes, so a new criterion or a new value
 * appears without a change here and is simply not translated yet.
 */
import { t, translateOr } from "@/lib/i18n";
import { DASH, fmtPct, localFixed, localInt } from "@/lib/i18n/format";
import { bogotaDateTime, toNum } from "./aiModel";

type Bag = Record<string, unknown>;

function isBag(value: unknown): value is Bag {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A value that is not a number the way a person would say it; a list says how many it has, an object nothing. */
function plain(value: unknown): string {
  if (value === null || value === undefined || value === "") return DASH;
  if (typeof value === "boolean") return value ? t("intel.match.yes") : t("intel.match.no");
  if (Array.isArray(value)) return t("intel.detail.nValues", { n: localInt(value.length) });
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? localFixed(value, 3) : DASH;
  return DASH;
}

// ── a calibrator's parameters ────────────────────────────────────────────────────────────────────────────────────────

const PARAM_ORDER = ["a", "b", "c"];

function rank(key: string): number {
  const at = PARAM_ORDER.indexOf(key);
  return at < 0 ? PARAM_ORDER.length : at;
}

/** "a 0,120 · b 0,950 · c -0,040": the coefficients of the fit, in the order they are applied; no coefficients, said so. */
export function calibratorParamsText(params: unknown): string {
  if (!isBag(params)) return DASH;
  const keys = Object.keys(params).sort(
    (x, y) => rank(x) - rank(y) || (x < y ? -1 : x > y ? 1 : 0),
  );
  if (keys.length === 0) return t("intel.detail.noParams");
  return keys.map((key) => `${key} ${plain(params[key])}`).join(" · ");
}

// ── the criteria fixed in advance ────────────────────────────────────────────────────────────────────────────────────

export interface GateLine {
  key: string;
  label: string;
  value: string;
}

export interface GateGroup {
  key: string;
  title: string;
  lines: GateLine[];
}

/** Criteria that are a return and not a count or a log loss: the expected value a rule asks for and the CLV it must show. */
const RELATIVE = new Set(["ev_rule", "min_rule_clv"]);

function gateValue(key: string, value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (RELATIVE.has(key)) return fmtPct(value, 1);
    return Number.isInteger(value) ? localInt(value) : localFixed(value, 3);
  }
  return plain(value);
}

function gateLine(key: string, value: unknown): GateLine {
  return {
    key,
    label: translateOr(`intel.calibration.gate.labels.${key}`, key),
    value: gateValue(key, value),
  };
}

/**
 * The gates the API sends ({ calib_gate: {...}, edge_gate: {...}, replace_gain, refit_every_days }) as groups of labelled lines:
 * every object is a group of its own and the loose numbers go together in "general".
 */
export function gateGroups(gates: unknown): GateGroup[] {
  if (!isBag(gates)) return [];
  const groups: GateGroup[] = [];
  const general: GateLine[] = [];
  for (const [key, value] of Object.entries(gates)) {
    if (isBag(value)) {
      groups.push({
        key,
        title: translateOr(`intel.calibration.gate.groups.${key}`, key),
        lines: Object.entries(value).map(([k, v]) => gateLine(k, v)),
      });
    } else {
      general.push(gateLine(key, value));
    }
  }
  if (general.length)
    groups.push({
      key: "general",
      title: t("intel.calibration.gate.groups.general"),
      lines: general,
    });
  return groups;
}

// ── the first leg of a tie ───────────────────────────────────────────────────────────────────────────────────────────

/** The words the dossier writes for what the second leg needs, and the key that says them in either language. */
const NEED: Record<string, string> = {
  "el local remonta": "home",
  "el visitante remonta": "away",
  "empate global": "level",
};

/**
 * "Ida 1–2 · el local remonta · 21 oct, 20:00": the first leg from the point of view of the home side of this match, what the
 * tie needs, and when it was played (Bogotá time, as the rest of this console).
 */
export function secondLegText(value: unknown): string {
  if (!isBag(value)) return DASH;
  const home = toNum(value["first_leg_score_home_side"] as number | string | null | undefined);
  const away = toNum(value["first_leg_score_away_side"] as number | string | null | undefined);
  const need = typeof value["aggregate_need"] === "string" ? value["aggregate_need"] : "";
  const at = typeof value["first_leg_at"] === "string" ? value["first_leg_at"] : "";
  const parts: string[] = [];
  if (home !== null && away !== null)
    parts.push(t("intel.match.firstLegScore", { home: localInt(home), away: localInt(away) }));
  if (need) parts.push(NEED[need] ? t(`intel.match.need.${NEED[need]}`) : need);
  if (at) parts.push(bogotaDateTime(at));
  return parts.length ? parts.join(" · ") : DASH;
}

// ── codes ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type CodeKind = "verdict" | "quality" | "method" | "result";

/**
 * A code of the post-mortem (its verdict and the quality of the decision), of a calibrator (its method) or of an outcome (win,
 * half_win...) in the reader's language; a code nobody has named yet comes back as it is, and nothing at all is a dash.
 */
export function codeText(kind: CodeKind, code: unknown): string {
  if (code === null || code === undefined || code === "") return DASH;
  const raw = String(code);
  const key = kind === "result" ? `admin.status.result.${raw}` : `intel.codes.${kind}.${raw}`;
  return translateOr(key, raw);
}
