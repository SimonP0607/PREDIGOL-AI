/**
 * The bundle's size budget (closing plan 5.2): the pure check. The script that reads the build's files is
 * scripts/bundle-budget.ts; the numbers are in web/bundle-budget.json. A byte count is gzip at level 6.
 */
export interface Budget {
  maxChunkJsGzip: number;
  maxTotalJsGzip: number;
  maxTotalCssGzip: number;
}

export interface Asset {
  name: string;
  gzip: number;
}

export interface Verdict {
  ok: boolean;
  problems: string[];
  largest: Asset | null;
  totalJs: number;
  totalCss: number;
}

const kb = (n: number) => `${Math.round(n / 1024)} KB`;

export function checkBudget(assets: readonly Asset[], budget: Budget): Verdict {
  const js = assets.filter((a) => a.name.endsWith(".js"));
  const css = assets.filter((a) => a.name.endsWith(".css"));
  const largest = js.reduce<Asset | null>((m, a) => (m === null || a.gzip > m.gzip ? a : m), null);
  const totalJs = js.reduce((n, a) => n + a.gzip, 0);
  const totalCss = css.reduce((n, a) => n + a.gzip, 0);
  const problems: string[] = [];
  if (largest && largest.gzip > budget.maxChunkJsGzip)
    problems.push(
      `el mayor fragmento de JS (${largest.name}) pesa ${kb(largest.gzip)} y el tope es ${kb(budget.maxChunkJsGzip)}`,
    );
  if (totalJs > budget.maxTotalJsGzip)
    problems.push(`todo el JS pesa ${kb(totalJs)} y el tope es ${kb(budget.maxTotalJsGzip)}`);
  if (totalCss > budget.maxTotalCssGzip)
    problems.push(`todo el CSS pesa ${kb(totalCss)} y el tope es ${kb(budget.maxTotalCssGzip)}`);
  if (js.length === 0) problems.push("no hay JS en la compilación: ¿se ejecutó `bun run build`?");
  return { ok: problems.length === 0, problems, largest, totalJs, totalCss };
}
