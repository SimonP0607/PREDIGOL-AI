/// <reference types="bun" />
/**
 * The product's error state says what failed, gives the request's reference and offers a retry (plan UX, A1, QA:
 * "UNIT: ... States"; defect F05: a failed read looked like an empty list). Never an empty list, never a raw code.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { LiveApiError } from "@/lib/api/v1/client";
import { setLocale } from "@/lib/i18n";
import { ErrorState, errorMessage } from "./States";

afterAll(() => setLocale("es"));

describe("ErrorState", () => {
  test("what failed, the reference of the request and a retry, as an alert", () => {
    setLocale("es");
    const error = new LiveApiError("boom", 500, "internal", "rid-123");
    const html = renderToStaticMarkup(<ErrorState error={error} onRetry={() => undefined} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Referencia: rid-123");
    expect(html).toContain("Reintentar");
    expect(html).not.toContain("internal");
  });

  test("no reference without a request id, and no retry without a way to retry", () => {
    const html = renderToStaticMarkup(<ErrorState error={new Error("x")} />);
    expect(html).not.toContain("Referencia");
    expect(html).not.toContain("<button");
  });

  test("the words of a known code, a generic message for an unknown one, the network's own when unreachable", () => {
    setLocale("es");
    expect(errorMessage(new LiveApiError("", 429, "too_many_attempts", null))).toContain(
      "Demasiados intentos",
    );
    expect(errorMessage(new LiveApiError("", 500, "some_new_code", null))).toBe(
      "No se pudo cargar esta información.",
    );
    expect(errorMessage(new LiveApiError("", 0, "network", null))).toBe(
      "No hay conexión con el servidor de PrediGol.",
    );
    setLocale("en");
    expect(errorMessage(new Error("x"))).toBe("This could not be loaded.");
  });
});
