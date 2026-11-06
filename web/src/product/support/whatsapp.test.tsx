/// <reference types="bun" />
/**
 * The WhatsApp chat's message (closing plan 4.2): the first line, then a code of where the reader was - the web's
 * version, the screen's path and, in an error, its reference - and nothing about the person; the number only in the
 * address's path; the contact's channels in the owner's order; the «Más» row only once the number exists.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { whatsappLink } from "@/product/membership/membership";
import { buildContext } from "./context";
import { contextCode, messageWithCode } from "./whatsapp";
import { WhatsappLink } from "./WhatsappLink";

afterAll(() => setLocale("es"));

const win = (pathname: string) => ({
  innerWidth: 390,
  matchMedia: () => ({ matches: false }) as MediaQueryList,
  location: { pathname },
});

describe("the context code", () => {
  test("version, screen and error reference - only the pieces that exist", () => {
    const withRef = buildContext({ requestId: "a1b2c3" }, win("/matches/812"));
    expect(contextCode({}, withRef)).toMatch(/^(v[\w.+-]+ · )?\/matches\/812 · ref a1b2c3$/);
    const bare = buildContext({ requestId: null }, win("/help"));
    const code = contextCode({}, bare);
    expect(code).toContain("/help");
    expect(code).not.toContain("ref ");
  });

  test("never the query, the fragment or anything of the person", () => {
    const ctx = buildContext({ requestId: "r1" }, win("/login?email=ana@example.com#x"));
    const code = contextCode({}, ctx);
    expect(code).not.toContain("@");
    expect(code).not.toContain("?");
    expect(code).not.toContain("#");
    expect(code).not.toContain("example");
  });

  test("the message is the line, a blank line and the code; no code, the line alone", () => {
    setLocale("es");
    expect(messageWithCode("Hola", "v1 · /help")).toBe("Hola\n\nCódigo de consulta: v1 · /help");
    expect(messageWithCode("Hola", "")).toBe("Hola");
    setLocale("en");
    expect(messageWithCode("Hello", "v1")).toBe("Hello\n\nReference: v1");
    setLocale("es");
  });

  test("the address carries the number and the encoded message, nothing else", () => {
    const href = whatsappLink("573001234567", messageWithCode("Hola", "v1 · /help · ref ab12"));
    expect(href.startsWith("https://wa.me/573001234567?text=")).toBe(true);
    expect(decodeURIComponent(href.split("text=")[1] ?? "")).toContain("ref ab12");
  });
});

describe("the link component", () => {
  test("it renders nothing without a number and an external, no-opener link with one", () => {
    const none = renderToStaticMarkup(
      <WhatsappLink digits={null} text="Hola">
        x
      </WhatsappLink>,
    );
    expect(none).toBe("");
    const out = renderToStaticMarkup(
      <WhatsappLink digits="573001234567" text="Hola" testId="w">
        x
      </WhatsappLink>,
    );
    expect(out).toContain('href="https://wa.me/573001234567?text=Hola"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('target="_blank"');
  });
});
