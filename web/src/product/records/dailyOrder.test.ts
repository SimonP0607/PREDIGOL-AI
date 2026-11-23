import { describe, expect, test } from "bun:test";
import { DEFAULT_DAILY_ORDER, orderDaily } from "./dailyOrder";

// El orden de la captura de la auditoría: 5, 2, 1, 3 (por hora).
const raw = [
  { rank: 5, ev: "0.05", match: { kickoff_at: "2026-11-10T16:00:00Z" } },
  { rank: 2, ev: "0.12", match: { kickoff_at: "2026-11-10T18:00:00Z" } },
  { rank: 1, ev: "0.148", match: { kickoff_at: "2026-11-10T23:30:00Z" } },
  { rank: 3, ev: "0.09", match: { kickoff_at: "2026-11-11T01:00:00Z" } },
];

describe("orderDaily", () => {
  test("por defecto, «Mejores primero»: 5, 2, 1, 3 → 1, 2, 3, 5", () => {
    expect(DEFAULT_DAILY_ORDER).toBe("best");
    expect(orderDaily(raw, DEFAULT_DAILY_ORDER).map((p) => p.rank)).toEqual([1, 2, 3, 5]);
  });

  test("«Por hora» sigue disponible", () => {
    expect(orderDaily(raw, "time").map((p) => p.rank)).toEqual([5, 2, 1, 3]);
  });

  test("«Por valor» sigue disponible y desempata por rango", () => {
    expect(orderDaily(raw, "value").map((p) => p.rank)).toEqual([1, 2, 3, 5]);
    const tie = [
      { rank: 2, ev: "0.1", match: { kickoff_at: "2026-11-10T18:00:00Z" } },
      { rank: 1, ev: "0.1", match: { kickoff_at: "2026-11-10T19:00:00Z" } },
    ];
    expect(orderDaily(tie, "value").map((p) => p.rank)).toEqual([1, 2]);
  });

  test("no modifica la lista de entrada", () => {
    const copy = JSON.stringify(raw);
    orderDaily(raw, "best");
    expect(JSON.stringify(raw)).toBe(copy);
  });
});
