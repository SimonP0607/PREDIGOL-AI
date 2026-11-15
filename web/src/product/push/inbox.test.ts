import { describe, expect, test } from "bun:test";
import { bellFigure, noticeTarget } from "./inbox";

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
