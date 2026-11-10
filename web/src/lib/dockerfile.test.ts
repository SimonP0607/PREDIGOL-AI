/// <reference types="bun" />
/**
 * The web image's recipe builds the app (OPS-004). OPS-003 joined a comment and the build step on one line with a
 * written backslash-n: Docker read the whole line as a comment, the image had no `.output` and every deploy that rebuilt
 * the web stopped at `COPY --from=build /app/.output` (10 Nov 2026, chain 1c2c50c; production untouched). Web CI does
 * not build this Dockerfile, so this reads it.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const recipe = readFileSync(join(import.meta.dir, "..", "..", "Dockerfile"), "utf8");
const lines = recipe.split("\n");

describe("web/Dockerfile", () => {
  test("the build is an instruction of its own, not part of a comment", () => {
    const build = lines.filter((l) => /^RUN\b.*\bbun run build\b/.test(l));
    expect(build.length).toBe(1);
    expect(build[0]).toContain("test -f .output/server/index.mjs");
  });

  test("no line carries a written backslash-n (two lines joined into one)", () => {
    expect(lines.filter((l) => l.includes("\\n"))).toEqual([]);
  });

  test("the image copies the output the build makes", () => {
    expect(recipe).toContain("COPY --from=build --chown=node:node /app/.output ./.output");
  });
});
