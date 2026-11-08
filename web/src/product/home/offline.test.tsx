/// <reference types="bun" />
/** Without a connection Inicio says so once, in a line; online - and on the server - it says nothing (plan de Inicio, 4.1). */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { OfflineNote } from "./offline";

describe("OfflineNote", () => {
  test("the server render and the first paint say nothing", () => {
    setLocale("es");
    expect(renderToStaticMarkup(<OfflineNote />)).toBe("");
  });
});
