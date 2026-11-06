/// <reference types="bun" />
import { readFileSync } from "node:fs";
import { describe, expect, test } from "bun:test";
import { checkBudget, type Budget } from "./bundleBudget";

const budget: Budget = { maxChunkJsGzip: 300, maxTotalJsGzip: 1000, maxTotalCssGzip: 50 };

describe("the bundle budget", () => {
  test("a build within the three limits passes", () => {
    const v = checkBudget(
      [
        { name: "a.js", gzip: 300 },
        { name: "b.js", gzip: 200 },
        { name: "s.css", gzip: 50 },
        { name: "logo.png", gzip: 99999 },
      ],
      budget,
    );
    expect(v.ok).toBe(true);
    expect(v.largest?.name).toBe("a.js");
    expect(v.totalJs).toBe(500);
  });

  test("one chunk over its limit fails and says which", () => {
    const v = checkBudget([{ name: "big.js", gzip: 301 }], budget);
    expect(v.ok).toBe(false);
    expect(v.problems.join(" ")).toContain("big.js");
  });

  test("the total of the JS and of the CSS fail on their own", () => {
    const many = Array.from({ length: 5 }, (_, i) => ({ name: `c${i}.js`, gzip: 250 }));
    expect(checkBudget(many, budget).problems.join(" ")).toContain("todo el JS");
    expect(
      checkBudget(
        [
          { name: "a.js", gzip: 1 },
          { name: "x.css", gzip: 51 },
        ],
        budget,
      ).problems.join(" "),
    ).toContain("todo el CSS");
  });

  test("an empty build is not a pass: there was nothing to measure", () => {
    expect(checkBudget([], budget).ok).toBe(false);
  });

  test("the budget file has the three limits, as positive numbers", () => {
    const file = JSON.parse(
      readFileSync(new URL("../../../bundle-budget.json", import.meta.url), "utf8"),
    ) as Record<string, unknown>;
    for (const key of ["maxChunkJsGzip", "maxTotalJsGzip", "maxTotalCssGzip"]) {
      expect(typeof file[key]).toBe("number");
      expect(file[key] as number).toBeGreaterThan(0);
    }
  });
});
