/**
 * DEMO DATA — market / odds layer.
 * Prices, consensus, movement and near-close snapshots are synthetic.
 */
import type {
  BookmakerPrice,
  ConsensusRow,
  LineMovementSeries,
  NearCloseRow,
  ValueRow,
} from "@/types/domain";
import { fixtures } from "./data";

const day = "2026-09-04";
const at = (hhmm: string) => `${day}T${hhmm}:00Z`;

export const bookmakers = ["Book A", "Book B", "Book C", "Book D", "Book E", "Book F"];

const implied = (o: number) => Number((1 / o).toFixed(4));

function price(
  bookmaker: string,
  market: BookmakerPrice["market"],
  marketLabel: string,
  selection: string,
  odds: number,
  capturedAt: string,
  freshness: BookmakerPrice["freshness"],
): BookmakerPrice {
  return {
    bookmaker,
    market,
    marketLabel,
    selection,
    odds,
    impliedProbability: implied(odds),
    capturedAt,
    freshness,
  };
}

const boardSeed: Record<string, Array<[string, string, number, string]>> = {
  "fx-10241": [
    ["Book A", "Home", 2.85, "12:03"],
    ["Book B", "Home", 2.88, "12:02"],
    ["Book C", "Home", 2.92, "12:03"],
    ["Book D", "Home", 2.8, "11:58"],
    ["Book E", "Home", 2.86, "12:01"],
    ["Book F", "Home", 2.79, "11:44"],
    ["Book A", "Draw", 3.7, "12:03"],
    ["Book B", "Draw", 3.6, "12:02"],
    ["Book C", "Draw", 3.65, "12:03"],
    ["Book D", "Draw", 3.55, "11:58"],
    ["Book E", "Draw", 3.62, "12:01"],
    ["Book F", "Draw", 3.5, "11:44"],
    ["Book A", "Away", 2.52, "12:03"],
    ["Book B", "Away", 2.6, "12:02"],
    ["Book C", "Away", 2.55, "12:03"],
    ["Book D", "Away", 2.58, "11:58"],
    ["Book E", "Away", 2.5, "12:01"],
    ["Book F", "Away", 2.46, "11:44"],
  ],
};

export function oddsBoard(fixtureId: string): BookmakerPrice[] {
  const seed = boardSeed[fixtureId] ?? boardSeed["fx-10241"]!;
  return seed.map(([book, selection, odds, hhmm]) => {
    const minutes = Number(hhmm!.slice(3));
    const freshness = minutes >= 12 ? "fresh" : minutes >= 58 ? "fresh" : "aging";
    return price(
      book!,
      "1x2",
      "1X2",
      selection!,
      odds!,
      at(hhmm!),
      hhmm === "11:44" ? "stale" : freshness,
    );
  });
}

export function consensus(fixtureId: string): ConsensusRow[] {
  const board = oddsBoard(fixtureId);
  const selections = ["Home", "Draw", "Away"];
  const rows: ConsensusRow[] = [];
  const rawTotal = selections.reduce((acc, s) => {
    const list = board.filter((b) => b.selection === s);
    const mean = list.reduce((a, b) => a + b.impliedProbability, 0) / list.length;
    return acc + mean;
  }, 0);
  for (const s of selections) {
    const list = board.filter((b) => b.selection === s).sort((a, b) => a.odds - b.odds);
    const best = list[list.length - 1]!;
    const median = list[Math.floor(list.length / 2)]!;
    const mean = list.reduce((a, b) => a + b.impliedProbability, 0) / list.length;
    rows.push({
      market: "1x2",
      marketLabel: "1X2",
      selection: s,
      marketProbability: Number((mean / rawTotal).toFixed(4)),
      bestOdds: best.odds,
      bestBookmaker: best.bookmaker,
      medianOdds: median.odds,
      bookmakerCount: list.length,
      overround: Number(rawTotal.toFixed(4)),
      capturedAt: at("12:03"),
      freshness: "fresh",
    });
  }
  return rows;
}

const movementTimes = ["08:00", "09:00", "10:00", "11:00", "11:30", "12:00", "12:03"];

export function lineMovement(fixtureId: string): LineMovementSeries[] {
  const base: Record<string, number[]> = {
    "Book A": [2.95, 2.94, 2.9, 2.88, 2.87, 2.86, 2.85],
    "Book C": [3.02, 3.0, 2.98, 2.95, 2.93, 2.92, 2.92],
    "Book D": [2.9, 2.88, 2.86, 2.84, 2.82, 2.81, 2.8],
    Consensus: [2.96, 2.94, 2.91, 2.89, 2.87, 2.86, 2.86],
  };
  const drift = fixtureId.endsWith("3") ? 0.05 : 0;
  return Object.entries(base).map(([bookmaker, series]) => ({
    bookmaker,
    points: series.map((odds, i) => ({
      at: at(movementTimes[i]!),
      odds: Number((odds + drift).toFixed(2)),
    })),
  }));
}

const valueSeed: Array<
  [
    string,
    ValueRow["market"],
    string,
    string,
    number,
    number,
    number,
    number,
    string,
    ValueRow["freshness"],
  ]
> = [
  [
    "fx-10241",
    "ou_2_5",
    "Over / Under 2.5",
    "Over 2.5",
    0.548,
    0.521,
    1.82,
    1.95,
    "Book D",
    "fresh",
  ],
  ["fx-10241", "1x2", "1X2", "Home", 0.372, 0.351, 2.69, 2.92, "Book C", "fresh"],
  ["fx-10242", "btts", "BTTS", "Yes", 0.604, 0.578, 1.66, 1.78, "Book B", "fresh"],
  ["fx-10244", "1x2", "1X2", "Home", 0.481, 0.462, 2.08, 2.2, "Book A", "aging"],
  [
    "fx-10246",
    "ou_2_5",
    "Over / Under 2.5",
    "Under 2.5",
    0.421,
    0.404,
    2.38,
    2.55,
    "Book E",
    "fresh",
  ],
  ["fx-10248", "double_chance", "Double Chance", "1X", 0.688, 0.671, 1.45, 1.5, "Book C", "aging"],
  ["fx-10243", "1x2", "1X2", "Away", 0.243, 0.219, 4.12, 4.6, "Book D", "stale"],
  ["fx-10245", "1x2", "1X2", "Draw", 0.271, 0.259, 3.69, 3.85, "Book F", "stale"],
];

export const valueRows: ValueRow[] = valueSeed.map(
  (
    [fixtureId, market, marketLabel, selection, modelP, marketP, fair, best, book, freshness],
    i,
  ) => {
    const fx = fixtures.find((f) => f.id === fixtureId)!;
    return {
      id: `val-${i + 1}`,
      fixtureId,
      fixtureLabel: `${fx.home.name} vs ${fx.away.name}`,
      competition: fx.competition.name,
      competitionCode: fx.competition.shortCode,
      kickoff: fx.kickoff,
      market,
      marketLabel,
      selection,
      modelProbability: modelP,
      marketProbability: marketP,
      fairOdds: fair,
      bestOdds: best,
      bookmaker: book,
      edge: Number((modelP - marketP).toFixed(4)),
      ev: Number((modelP * best - 1).toFixed(4)),
      freshness,
    };
  },
);

export const nearCloseRows: NearCloseRow[] = [
  {
    fixtureId: "fx-10247",
    fixtureLabel: "Aston Villa vs Everton",
    market: "1x2",
    marketLabel: "1X2",
    selection: "Home",
    capturedAt: at("13:48"),
    minutesToKickoff: 12,
    snapshotOdds: 1.94,
    latestOdds: 1.91,
    delta: -0.03,
    validated: false,
  },
  {
    fixtureId: "fx-10247",
    fixtureLabel: "Aston Villa vs Everton",
    market: "ou_2_5",
    marketLabel: "Over / Under 2.5",
    selection: "Over 2.5",
    capturedAt: at("13:48"),
    minutesToKickoff: 12,
    snapshotOdds: 1.86,
    latestOdds: 1.88,
    delta: 0.02,
    validated: false,
  },
  {
    fixtureId: "fx-10244",
    fixtureLabel: "Stuttgart vs Freiburg",
    market: "1x2",
    marketLabel: "1X2",
    selection: "Home",
    capturedAt: at("16:18"),
    minutesToKickoff: 12,
    snapshotOdds: 2.2,
    latestOdds: 2.16,
    delta: -0.04,
    validated: false,
  },
];
