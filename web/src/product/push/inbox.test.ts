import { describe, expect, test } from "bun:test";
import { t } from "@/lib/i18n";
import type { InboxItem } from "@/lib/api/v1/types_inbox";
import { bellFigure, groupByDay, noticeDay, noticeTarget } from "./inbox";

describe("«Avisos» (decision 1)", () => {
  test("the bell writes nothing at zero and «9+» beyond nine", () => {
    expect(bellFigure(0)).toBeNull();
    expect(bellFigure(-1)).toBeNull();
    expect(bellFigure(1)).toBe("1");
    expect(bellFigure(9)).toBe("9");
    expect(bellFigure(10)).toBe("9+");
  });
  test("a notice opens a page of PrediGol, never another site", () => {
    expect(noticeTarget("/matches/7#postmatch")).toEqual({ path: "/matches/7", hash: "postmatch" });
    expect(noticeTarget("/my-picks")).toEqual({ path: "/my-picks" });
    expect(noticeTarget("/matches/7?notice=result#postmatch")).toEqual({
      path: "/matches/7",
      hash: "postmatch",
    });
    expect(noticeTarget("//evil.example/x")).toEqual({ path: "/home" });
    expect(noticeTarget("https://evil.example")).toEqual({ path: "/home" });
    expect(noticeTarget("")).toEqual({ path: "/home" });
  });
});

describe("«Avisos» agrupados por día (UX-250, decisión C-02)", () => {
  const now = new Date(2026, 10, 26, 15, 0, 0); // 26-nov-2026, 15:00 local
  const at = (d: number, h = 9) => new Date(2026, 10, d, h, 0, 0).toISOString();
  const item = (id: number, when: string): InboxItem => ({
    id,
    category: "result",
    title: `n${id}`,
    body: "",
    url: "/home",
    at: when,
    read: false,
  });

  test("hoy, ayer, esta semana y antes, por el día del lector, no por las últimas 24 horas", () => {
    expect(noticeDay(at(26, 0), now)).toBe("today");
    expect(noticeDay(at(25, 23), now)).toBe("yesterday");
    expect(noticeDay(at(25, 0), now)).toBe("yesterday");
    expect(noticeDay(at(24), now)).toBe("week");
    expect(noticeDay(at(19), now)).toBe("week");
    expect(noticeDay(at(18), now)).toBe("earlier");
    expect(noticeDay(at(1), now)).toBe("earlier");
  });

  test("un aviso con hora algo adelantada sigue siendo de hoy y una fecha ilegible va a «Antes»", () => {
    expect(noticeDay(new Date(2026, 10, 26, 15, 0, 30).toISOString(), now)).toBe("today");
    expect(noticeDay("not-a-date", now)).toBe("earlier");
  });

  test("los grupos salen en orden, cada uno con sus avisos en el orden del servidor, y no hay grupos vacíos", () => {
    const groups = groupByDay(
      [item(1, at(26, 12)), item(2, at(26, 8)), item(3, at(24)), item(4, at(2))],
      now,
    );
    expect(groups.map((g) => g.day)).toEqual(["today", "week", "earlier"]);
    expect(groups[0]!.items.map((i) => i.id)).toEqual([1, 2]);
    expect(groupByDay([], now)).toEqual([]);
  });

  test("cada grupo tiene su palabra en español", () => {
    for (const d of ["today", "yesterday", "week", "earlier"]) {
      expect(t(`push.inbox.group.${d}`)).not.toContain("push.inbox.group");
    }
  });
});
