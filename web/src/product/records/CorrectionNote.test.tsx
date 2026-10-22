/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { ResultCorrection } from "@/lib/api/v1/types_records";
import { CorrectionNote } from "./CorrectionNote";

const TWO_HOURS_AGO = new Date(Date.now() - 2 * 3_600_000).toISOString();

function correction(over: Partial<ResultCorrection> = {}): ResultCorrection {
  return {
    at: TWO_HOURS_AGO,
    leg_no: null,
    from_status: "WIN",
    to_status: "LOSS",
    from_profit: "1.3000",
    to_profit: "-1.0000",
    cause: "result_corrected",
    ...over,
  };
}

function words(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

describe("a result corrected after it was settled says so (plan F0, defect 5)", () => {
  test("a record never corrected shows nothing at all", () => {
    expect(renderToStaticMarkup(<CorrectionNote corrections={[]} record="result" />)).toBe("");
    expect(renderToStaticMarkup(<CorrectionNote corrections={undefined} record="result" />)).toBe(
      "",
    );
    expect(renderToStaticMarkup(<CorrectionNote corrections={null} record="parlay" />)).toBe("");
  });

  test("a pick: what it had been, in the reader's language", () => {
    setLocale("es");
    const es = words(<CorrectionNote corrections={[correction()]} record="result" />);
    expect(es).toContain("Resultado corregido");
    expect(es).toContain("Ganado → Perdido");
    setLocale("en");
    const en = words(<CorrectionNote corrections={[correction()]} record="result" />);
    expect(en).toContain("Result corrected");
    expect(en).not.toContain("Resultado");
    setLocale("es");
  });

  test("a parlay uses the parlay's words and its legs the legs' words", () => {
    setLocale("es");
    const html = words(
      <CorrectionNote
        corrections={[
          correction({ leg_no: 2, from_status: "WIN", to_status: "LOSS" }),
          correction({ from_status: "WON", to_status: "LOST" }),
        ]}
        record="parlay"
      />,
    );
    expect(html).toContain("Selección 2: ");
    expect(html).toContain("Ganado → Perdido");
    expect(html).toContain("Ganada → Perdida");
  });

  test("a parlay that a corrected leg no longer decides is back in play", () => {
    setLocale("es");
    const html = words(
      <CorrectionNote
        corrections={[correction({ from_status: "LOST", to_status: "ACTIVE" })]}
        record="parlay"
      />,
    );
    expect(html).toContain("Perdida → En juego");
  });

  test("only the latest corrections are listed; the rest are counted", () => {
    setLocale("es");
    const five = [1, 2, 3, 4, 5].map((n) => correction({ at: `2032-08-0${n}T10:00:00Z` }));
    const markup = renderToStaticMarkup(<CorrectionNote corrections={five} record="result" />);
    expect(markup.match(/<li/g)?.length).toBe(3);
    expect(words(<CorrectionNote corrections={five} record="result" />)).toContain("y 2 más");
  });

  test("whoever hovers a line is told why, in their language - never the backend's own words", () => {
    const title = (cause: ResultCorrection["cause"]) =>
      renderToStaticMarkup(
        <CorrectionNote corrections={[correction({ cause })]} record="result" />,
      ).match(/<li[^>]*title="([^"]*)"/)?.[1];
    setLocale("es");
    expect(title("result_corrected")).toBe(
      "El proveedor de datos corrigió el marcador del partido y este registro se liquidó de nuevo.",
    );
    expect(title("status_changed")).toContain("Cambió el estado del partido");
    expect(title("audit")).toContain("Una revisión comprobó");
    setLocale("en");
    expect(title("result_corrected")).toBe(
      "The data provider corrected the match score and this record was settled again.",
    );
    expect(title("status_changed")).toContain("The match status changed");
    expect(title("audit")).toContain("A review found");
    // a cause this screen does not know yet: the note's own explanation, not a raw key
    expect(title("something_new" as never)).toBe(
      "This record changed result after it was settled: it was settled again and what it said before is kept here.",
    );
    setLocale("es");
  });

  test("a status without a word is shown as it came", () => {
    setLocale("en");
    expect(
      words(
        <CorrectionNote
          corrections={[correction({ to_status: "SOMETHING_NEW" as never })]}
          record="result"
        />,
      ),
    ).toContain("Won → SOMETHING_NEW");
    setLocale("es");
  });
});
