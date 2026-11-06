/**
 * `bun scripts/bundle-budget.ts` after `bun run build` (closing plan 5.2): fails if the build is over the budget of
 * web/bundle-budget.json. The check itself is src/lib/perf/bundleBudget.ts.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { checkBudget, type Budget } from "../src/lib/perf/bundleBudget";

const dir = join(import.meta.dir, "..", ".output", "public", "assets");
const budget = JSON.parse(
  readFileSync(join(import.meta.dir, "..", "bundle-budget.json"), "utf8"),
) as Budget;
const assets = readdirSync(dir)
  .filter((n) => n.endsWith(".js") || n.endsWith(".css"))
  .map((name) => ({ name, gzip: gzipSync(readFileSync(join(dir, name)), { level: 6 }).length }));
const verdict = checkBudget(assets, budget);
const kb = (n: number) => `${Math.round(n / 1024)} KB`;
console.log(
  `JS ${kb(verdict.totalJs)} / ${kb(budget.maxTotalJsGzip)} · mayor fragmento ${verdict.largest?.name ?? "-"} ${kb(verdict.largest?.gzip ?? 0)} / ${kb(budget.maxChunkJsGzip)} · CSS ${kb(verdict.totalCss)} / ${kb(budget.maxTotalCssGzip)}`,
);
if (!verdict.ok) {
  for (const p of verdict.problems) console.error(`✗ ${p}`);
  process.exit(1);
}
console.log("✓ dentro del presupuesto");
