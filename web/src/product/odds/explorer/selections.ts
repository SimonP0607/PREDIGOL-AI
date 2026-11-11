/**
 * A selection in words, and the price figures beside it. Pure.
 *
 * Every selection reads at ITS OWN line: an Asian handicap's two sides are two faces of one bet, «Local -0,25 · Visitante
 * +0,25» (plan Cuotas, E1); a European handicap's three ways sit at the home handicap, the away side at its opposite. The
 * figures never mix (plan, section 5): «Mejor cuota · Casa», «Justa del mercado», «+1,4 % sobre la justa» in grey - and no
 * model figure anywhere.
 */
import { t } from "@/lib/i18n";
import { fmtLine, formatOdds, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { parseMarketKey, shapeOf, type Shape } from "./markets";
import type { Dec, OddsMarketInfo, OddsSelectionPrice } from "./model";

export interface Sides {
  home: string;
  away: string;
}

export type LabelForm = "short" | "full";

/** The result markets: their selections are 1, X and 2 (the result half of «resultado y ambos marcan» too). */
const RESULT_LIKE = new Set([
  "result.1x2",
  "result.draw_no_bet",
  "corners.1x2",
  "shots.1x2",
  "shots.on_target_1x2",
  "goals.result_btts",
  "halves.ht_ft",
]);

/** The provider's words the book keeps (tax-v3 vocabularies) -> the explorer's key for them. */
const TOKEN_KEY: Readonly<Record<string, string>> = {
  Home: "home",
  Away: "away",
  Draw: "draw",
  Over: "over",
  Under: "under",
  Exactly: "exactly",
  Yes: "yes",
  No: "no",
  Odd: "odd",
  Even: "even",
  "No goal": "noGoal",
  "1st Half": "firstHalf",
  "2nd Half": "secondHalf",
  "Score Draw": "scoreDraw",
  Shot: "shot",
  Header: "header",
  Penalty: "penalty",
  FreeKick: "freeKick",
  OwnGoal: "ownGoal",
  "No Goalscorer": "noGoalscorer",
};

function word(token: string): string {
  const key = TOKEN_KEY[token];
  return key ? t(`explorer.sel.${key}`) : token;
}

const RESULT_SHORT: Readonly<Record<string, string>> = { Home: "1", Draw: "X", Away: "2" };

function team(token: string, sides: Sides, form: LabelForm): string | null {
  if (token === "Home") return form === "full" ? sides.home : word("Home");
  if (token === "Away") return form === "full" ? sides.away : word("Away");
  return null;
}

/** A handicap or a total: "-0,25", "+1", "2,5". */
function lineText(line: number | null, signed: boolean): string {
  return line === null ? "" : fmtLine(line, signed);
}

/**
 * The line a selection is at. An Asian handicap: its own (the API sends it; without it the away side is the opposite of the
 * row's home line). A European handicap: the home handicap for home and draw, its opposite for the away side, whatever the
 * selection carries (the provider prints the home number on all three). Any other: its own, else the row's.
 */
export function ownLine(
  shape: Shape,
  sel: Pick<OddsSelectionPrice, "selection" | "line">,
  rowLine: Dec | null,
): number | null {
  const own = toNumber(sel.line);
  const row = toNumber(rowLine);
  const flip = (n: number | null) => (n === null ? null : n === 0 ? 0 : -n);
  if (shape === "eh") {
    const home = row ?? own;
    return sel.selection === "Away" ? flip(home) : home;
  }
  if (shape === "ah") {
    if (own !== null) return own === 0 ? 0 : own;
    return sel.selection === "Away" ? flip(row) : row;
  }
  return own ?? row;
}

const MARGIN = /^([12]) by (\d+\+?)$/;

function plainLabel(base: string, token: string, sides: Sides, form: LabelForm): string {
  // A pair of words: half-time / full-time («1/X»), result and both score («1 / Sí»).
  if (token.includes("/")) {
    const glue = form === "short" && base === "halves.ht_ft" ? "/" : " / ";
    return token
      .split("/")
      .map((part) => plainLabel(base, part, sides, form))
      .join(glue);
  }
  if (RESULT_LIKE.has(base)) {
    if (form === "short" && token in RESULT_SHORT) return RESULT_SHORT[token] as string;
    if (token === "Draw") return word("Draw");
  }
  if (base === "cards.first_card" && token === "Draw") return t("explorer.sel.noCard");
  if (base.startsWith("halves.highest_scoring") && token === "Draw") return t("explorer.sel.tie");
  if (token === "1X" || token === "12" || token === "X2") {
    return form === "short" ? token : t(`explorer.sel.dc${token}`, { ...sides });
  }
  const margin = MARGIN.exec(token);
  if (margin) {
    const side = margin[1] === "1" ? "Home" : "Away";
    return t("explorer.sel.byGoals", {
      team: team(side, sides, form) ?? side,
      n: margin[2],
    });
  }
  return team(token, sides, form) ?? word(token);
}

/**
 * The selection in words. `short`: the board's cell («1», «Más 2,5», «Local -0,25», «2:1»); `full`: the same with the teams'
 * names, for a screen reader and the comparison («Brighton -0,25»).
 */
export function selectionLabel(
  info: Pick<OddsMarketInfo, "key" | "kind">,
  sel: Pick<OddsSelectionPrice, "selection" | "player" | "line">,
  rowLine: Dec | null,
  sides: Sides,
  form: LabelForm = "short",
): string {
  const shape = shapeOf(info);
  const { base } = parseMarketKey(info.key);
  const token = sel.selection;
  const line = ownLine(shape, sel, rowLine);
  switch (shape) {
    case "ah": {
      const side = team(token, sides, form) ?? word(token);
      return `${side} ${lineText(line, true)}`.trim();
    }
    case "eh": {
      const text = lineText(line, true);
      if (token === "Draw") return t("explorer.sel.drawAt", { line: text });
      return `${team(token, sides, form) ?? word(token)} ${text}`.trim();
    }
    case "line":
      return `${word(token)} ${lineText(line, false)}`.trim();
    case "race": {
      const n = lineText(line, false);
      if (token === "Draw") return t("explorer.sel.raceNone", { n });
      return t("explorer.sel.raceFirst", { team: team(token, sides, form) ?? token, n });
    }
    case "result_total":
    case "total_btts": {
      const [a = token, b = ""] = token.split("/");
      const total = shape === "total_btts" ? a : b;
      const other = shape === "total_btts" ? b : a;
      const totalText = `${word(total)} ${lineText(line, false)}`.trim();
      const otherText = plainLabel(
        shape === "result_total" ? "result.1x2" : base,
        other,
        sides,
        form,
      );
      return shape === "total_btts" ? `${totalText} / ${otherText}` : `${otherText} / ${totalText}`;
    }
    case "ht_ft":
      return plainLabel("halves.ht_ft", token, sides, form);
    case "range":
      return token.replace(/^(\d+)-(\d+)$/, "$1–$2");
    case "exact_score":
    case "count":
      return token;
    case "player":
      return sel.player ?? word(token);
    case "player_count": {
      const name = sel.player ?? token;
      return line === null ? name : t("explorer.sel.atLeast", { name, n: lineText(line, false) });
    }
    default:
      return plainLabel(base, token, sides, form);
  }
}

/** «+1,4 % sobre la justa», «-2,1 % bajo la justa»: how far the best price sits from the market's fair price. Grey, always. */
export function edgeText(edge: Dec | number | null | undefined): string | null {
  const n = toNumber(edge);
  if (n === null) return null;
  const pct = fmtSignedPct(n);
  if (Math.abs(n) < 0.0005) return t("explorer.price.evenWithFair");
  return n > 0 ? t("explorer.price.overFair", { pct }) : t("explorer.price.underFair", { pct });
}

/**
 * What a screen reader hears of one price: the selection, the best price and its bookmaker, how many bookmakers quote it and,
 * only where there is one, the market's fair price and the difference with it.
 */
export function priceDescription(
  label: string,
  sel: Pick<OddsSelectionPrice, "best_odds" | "n_books" | "fair_odds" | "price_edge">,
  bookmaker: string,
): string {
  const head = t("explorer.price.sr", {
    selection: label,
    odds: formatOdds(sel.best_odds),
    bookmaker,
    count: sel.n_books,
  });
  const edge = edgeText(sel.price_edge);
  if (toNumber(sel.fair_odds) === null) return head;
  return `${head} ${t("explorer.price.srFair", { fair: formatOdds(sel.fair_odds) })}${edge ? ` ${edge}.` : ""}`;
}
