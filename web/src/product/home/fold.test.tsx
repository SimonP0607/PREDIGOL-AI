/// <reference types="bun" />
/**
 * A list short on a phone (plan de Inicio, 4.1): the rows past the kept ones are hidden by the width only and a «Ver N más»
 * button - phones only - opens them; a list that fits shows no button.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { useFold } from "./fold";

setLocale("es");

function List({ total, keep }: { total: number; keep: number }) {
  const fold = useFold(total, keep);
  return (
    <div>
      <ul>
        {Array.from({ length: total }, (_, i) => (
          <li key={i} className={fold.row(i)}>
            {i}
          </li>
        ))}
      </ul>
      {fold.more}
    </div>
  );
}

describe("useFold", () => {
  test("six rows, four kept: two hidden on a phone and a button that says how many", () => {
    const markup = renderToStaticMarkup(<List total={6} keep={4} />);
    expect(markup.match(/class="max-sm:hidden"/g)).toHaveLength(2);
    expect(markup).toContain("Ver 2 más");
    expect(markup).toContain("sm:hidden");
  });

  test("a list that fits has no hidden row and no button", () => {
    const markup = renderToStaticMarkup(<List total={3} keep={3} />);
    expect(markup).not.toContain("max-sm:hidden");
    expect(markup).not.toContain("fold-more");
  });
});
