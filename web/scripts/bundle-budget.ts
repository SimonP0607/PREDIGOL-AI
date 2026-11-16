/**
 * `bun scripts/bundle-budget.ts` after `bun run build` (closing plan 5.2): fails if the build is over the budget of
 * web/bundle-budget.json. The check itself is src/lib/perf/bundleBudget.ts.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
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
// The first visit's JS: the root route's preloads in TanStack Start's server manifest (UX-139).
const server = join(import.meta.dir, "..", ".output", "server");
const manifest = existsSync(server)
  ? readdirSync(server).find((n) => n.startsWith("_tanstack-start-manifest") && n.endsWith(".mjs"))
  : undefined;
let initial: string[] = [];
if (manifest) {
  const text = readFileSync(join(server, manifest), "utf8");
  const root = text.slice(text.indexOf("__root__"));
  const preloads = root.slice(
    root.indexOf("preloads: ["),
    root.indexOf("]", root.indexOf("preloads: [")),
  );
  initial = [...preloads.matchAll(/"\/assets\/([^"]+\.js)"/g)].map((m) => m[1]!);
}
const verdict = checkBudget(assets, budget, initial);
const kb = (n: number) => `${Math.round(n / 1024)} KB`;
console.log(
  `Arranque ${kb(verdict.initialJs)} / ${kb(budget.maxInitialJsGzip ?? 0)} · JS ${kb(verdict.totalJs)} / ${kb(budget.maxTotalJsGzip)} · mayor fragmento ${verdict.largest?.name ?? "-"} ${kb(verdict.largest?.gzip ?? 0)} / ${kb(budget.maxChunkJsGzip)} · CSS ${kb(verdict.totalCss)} / ${kb(budget.maxTotalCssGzip)}`,
);
if (!verdict.ok) {
  for (const p of verdict.problems) console.error(`✗ ${p}`);
  process.exit(1);
}
console.log("✓ dentro del presupuesto");
