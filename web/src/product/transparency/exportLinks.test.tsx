/// <reference types="bun" />
/** The download of the published picks (plan PM, PM-14-08): off draws nothing, on draws three plain links to the files. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { transparencyExportUrl } from "@/lib/api/v1/client";
import { setLocale } from "@/lib/i18n";
import { ExportLinks, ExportLinksView } from "./ExportLinks";

setLocale("es");

describe("the download of the published picks", () => {
  test("the addresses of the three files, and the owner's preview carried along", () => {
    expect(transparencyExportUrl("picks")).toBe("/api/v1/transparency/export");
    expect(transparencyExportUrl("calibration")).toBe(
      "/api/v1/transparency/export?part=calibration",
    );
    expect(transparencyExportUrl("json")).toBe("/api/v1/transparency/export?format=json");
    expect(transparencyExportUrl("picks", "shadow")).toBe(
      "/api/v1/transparency/export?preview=shadow",
    );
  });

  test("with the switch off nothing is drawn", () => {
    expect(renderToStaticMarkup(<ExportLinks />)).toBe("");
  });

  test("the owner's preview draws the links", () => {
    const html = renderToStaticMarkup(<ExportLinks preview="shadow" />);
    expect(html).toContain("preview=shadow");
  });

  test("three links, to files, without a word about returns", () => {
    const html = renderToStaticMarkup(<ExportLinksView />);
    expect(html.match(/<a /g)).toHaveLength(3);
    expect(html).toContain('href="/api/v1/transparency/export?part=calibration"');
    expect(html).toContain("intervalo del 95");
    expect(html.toLowerCase()).not.toContain("roi");
    expect(html.toLowerCase()).not.toContain("rentab");
  });
});
