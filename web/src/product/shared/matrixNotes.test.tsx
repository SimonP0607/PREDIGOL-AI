/// <reference types="bun" />
/** The module lines are born off (PM-14-04): outside a signed-in provider every module is `off`, draws nothing and asks C-16 nothing. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MATRIX_MODULES, MatrixNotes } from "./matrixModules";

describe("MatrixNotes while the line is off", () => {
  test.each(MATRIX_MODULES)("%s draws nothing and makes no request", (module) => {
    const client = new QueryClient();
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MatrixNotes module={module} fixtureId={1} />
      </QueryClientProvider>,
    );
    expect(html).toBe("");
    for (const q of client.getQueryCache().getAll()) expect(q.state.fetchStatus).toBe("idle");
  });
});
