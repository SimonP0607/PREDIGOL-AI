/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import { FunnelLine } from "./FunnelLine";

setLocale("es");

async function html(): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <FunnelLine /> }),
    history: createMemoryHistory({ initialEntries: ["/picks"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

describe("how a pick of the day gets here (REVIEW B1)", () => {
  test("every step, the risk cap and PrediGol Intelligence - never a model's name", async () => {
    const page = (await html()).replace(/<[^>]+>/g, " ");
    for (const step of [
      "Datos válidos",
      "Mercado",
      "Modelo",
      "Calibración",
      "Valor",
      "Riesgo (cuota ≤ 3,00)",
      "PrediGol Intelligence",
      "Selección (máx. 5)",
    ]) {
      expect(page).toContain(step);
    }
    expect(page).not.toMatch(/elo_ologit|dixon|poisson/i);
  });

  test("a card with its steps as a list and the way to the methodology (sheets K01, K08)", async () => {
    const page = await html();
    expect(page).toContain('data-testid="daily-funnel"');
    expect(page).toContain("/transparency/methodology");
    expect((page.match(/<li/g) ?? []).length).toBe(8);
  });
});
