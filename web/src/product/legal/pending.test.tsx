/// <reference types="bun" />
/**
 * Plan PM, PM-14-05 (FE-007): while a legal text loads, its skeleton keeps a screen's height, so that the footer does not show under
 * three short lines and jump when the text arrives (measured on a phone: CLS 0.125 → 0 on /legal/terms).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "@/lib/i18n";
import { LegalPage } from "./LegalPage";

describe("the legal page while its text loads", () => {
  test("the skeleton holds a screen's height", () => {
    const client = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">
          <LegalPage document="terms" />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(html).toContain('data-testid="legal-pending"');
    expect(html).toMatch(/class="[^"]*min-h-\[100dvh\][^"]*"[^>]*aria-busy="true"/);
  });
});
