/// <reference types="bun" />
/**
 * The guard of the news as stories (plan de correcciones UX, AP-N05 and AP-N06; contrato C-06): no screen of the stories reads the
 * author of a source or any picture - the author stays a `Missing` until the lawyer answers, the picture is a monogram - and
 * no address from the API is made a link without going through `safeUrl`.
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const dir = import.meta.dir;
const screens = readdirSync(dir).filter(
  (n) => /^(Story|Stories|MatchStories)\w*\.tsx$/.test(n) && !n.endsWith(".test.tsx"),
);
const read = (n: string) => readFileSync(join(dir, n), "utf8");

describe("the stories' screens", () => {
  test("there are screens to guard", () => {
    expect(screens.length).toBeGreaterThanOrEqual(4);
  });
  test("none reads a source's author or draws an image of a third party", () => {
    for (const n of screens) {
      const code = read(n);
      expect({ n, author: /\.author\b/.test(code) }).toEqual({ n, author: false });
      expect({ n, img: /<img\b|background-image|\.picture\b|\.image_url\b/.test(code) }).toEqual({
        n,
        img: false,
      });
    }
  });
  test("a link to a source goes through safeUrl", () => {
    for (const n of screens) {
      const code = read(n);
      if (/href=\{/.test(code) && /\.url\b/.test(code))
        expect({ n, safe: code.includes("safeUrl(") }).toEqual({ n, safe: true });
    }
  });
  test("a link out opens in a new tab without the opener", () => {
    for (const n of screens) {
      const code = read(n);
      if (/target="_blank"/.test(code))
        expect({ n, rel: code.includes('rel="noopener noreferrer"') }).toEqual({ n, rel: true });
    }
  });
});
