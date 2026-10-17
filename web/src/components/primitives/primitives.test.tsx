/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026), the Admin Console on a tablet: a key-value row cut its value ("0 · 16 hr ago"
 * read "0· 16…") and, by cutting, clipped the finger-sized reach of an explained "—" to 7 x 16 px; a table header
 * with a definition in it was too short for the definition's reach under the table's scroll box (38 px).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { KeyValue } from "./Panel";
import { TH } from "./DataTable";

describe("admin primitives on a touch screen", () => {
  test("a key-value row shows its whole value: it wraps, it is never cut", () => {
    const html = renderToStaticMarkup(<KeyValue label="Last run" value="0 · 16 hr ago" />);
    expect(html).toContain("0 · 16 hr ago");
    expect(html).not.toContain("truncate");
    expect(html).toContain("break-words");
  });

  test("a header cell with a control in it is a 44 px row on a touch screen", () => {
    const html = renderToStaticMarkup(
      <table>
        <thead>
          <tr>
            <TH>EV</TH>
          </tr>
        </thead>
      </table>,
    );
    expect(html).toContain("pointer-coarse:has-[button]:h-11");
  });
});
