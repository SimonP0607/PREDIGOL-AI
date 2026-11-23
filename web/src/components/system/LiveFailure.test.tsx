/// <reference types="bun" />
/**
 * AP-A02 (audit finding A3): a console section whose question failed says so on its own - the code of the error, the
 * request and a «Reintentar» - and never waits forever behind a skeleton or leaves a blank screen.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { LiveApiError } from "@/lib/api/v1/client";
import { setLocale } from "@/lib/i18n";
import { ApiErrorNotice, FailedOrSkeleton } from "./LiveState";

afterEach(() => setLocale("es"));

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const boom = new LiveApiError("Internal error", 500, "internal_error", "req-123");
const SKELETON = <div data-testid="skeleton">…</div>;

function gate(isError: boolean, error: unknown = boom): string {
  return renderToStaticMarkup(
    <FailedOrSkeleton
      isError={isError}
      error={error}
      onRetry={() => {}}
      retrying={false}
      skeleton={SKELETON}
    />,
  );
}

describe("a section that failed", () => {
  test("es: the code, the HTTP status, the request and a retry button; no skeleton", () => {
    setLocale("es");
    const html = gate(true);
    expect(html).toContain('data-testid="section-failed"');
    expect(html).toContain('data-testid="api-error-retry"');
    expect(html).not.toContain('data-testid="skeleton"');
    const t = text(html);
    expect(t).toContain("Código: internal_error (HTTP 500)");
    expect(t).toContain("petición req-123");
    expect(t).toContain("Reintentar");
  });

  test("en: the same, in English", () => {
    setLocale("en");
    const t = text(gate(true));
    expect(t).toContain("Code: internal_error (HTTP 500)");
    expect(t).toContain("Retry");
  });

  test("a section still on its way keeps its own skeleton, without an error", () => {
    const html = gate(false, null);
    expect(html).toContain('data-testid="skeleton"');
    expect(html).not.toContain("section-failed");
    expect(html).not.toContain("api-error-retry");
  });

  test("an error that is not the API's still says something and retries", () => {
    setLocale("es");
    const html = gate(true, new Error("boom"));
    expect(text(html)).toContain("Error inesperado.");
    expect(html).toContain('data-testid="api-error-retry"');
  });

  test("while it retries the button waits", () => {
    const html = renderToStaticMarkup(<ApiErrorNotice error={boom} onRetry={() => {}} retrying />);
    expect(html).toContain("disabled");
    expect(text(html)).toContain("Reintentando…");
  });

  test("without a retry the notice is as before (no button)", () => {
    const html = renderToStaticMarkup(<ApiErrorNotice error={boom} />);
    expect(html).not.toContain("api-error-retry");
  });
});
