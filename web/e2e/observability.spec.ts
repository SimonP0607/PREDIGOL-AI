/**
 * Error reporting end to end (plan UX, A2), as the owner checks it: the console's two test errors reach "Sentry" -
 * the API's under the reference the console shows, the browser's through the API's tunnel - and an error the page
 * throws with personal data in its message arrives without it. "Sentry" is a local stand-in that writes every
 * envelope it receives to a file (E2E_SENTRY_SINK; qa/fake_sentry.py with the QA API's Sentry pointed at it):
 * without it these checks are skipped.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { credentials } from "./accounts";

const SINK = process.env["E2E_SENTRY_SINK"];
test.skip(!SINK, "needs the local Sentry stand-in (E2E_SENTRY_SINK)");

type Item = { type: string; payload: Record<string, unknown> };
type Record_ = { path: string; header: Record<string, unknown>; items: Item[] };

function received(): Record_[] {
  try {
    return readFileSync(SINK as string, "utf-8")
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Record_);
  } catch {
    return [];
  }
}

function events(): { path: string; event: Record<string, unknown> }[] {
  return received().flatMap((r) =>
    r.items.filter((i) => i.type === "event").map((i) => ({ path: r.path, event: i.payload })),
  );
}

async function waitFor<T>(find: () => T | undefined, what: string): Promise<T> {
  for (let i = 0; i < 40; i++) {
    const found = find();
    if (found !== undefined) return found;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`nothing reached the stand-in: ${what}`);
}

function exceptionOf(event: Record<string, unknown>): { type?: string; value?: string } {
  const values =
    (event["exception"] as { values?: { type?: string; value?: string }[] } | undefined)?.values ??
    [];
  return values[values.length - 1] ?? {};
}

async function sessionCookie(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name.includes("predigol_session"))?.value ?? "no-cookie";
}

test.beforeEach(() => writeFileSync(SINK as string, ""));

test("the owner's two test errors arrive: the API's under its reference, the web's through the tunnel, nothing personal", async ({
  page,
}) => {
  await page.goto("/admin/system");
  await expect(page.getByTestId("synthetic-panel")).toBeVisible();
  await page.getByTestId("obs-api-test").click();
  const result = page.getByTestId("obs-api-result");
  await expect(result).toContainText(/reference [0-9a-f]{6,}/i);
  const reference = /reference ([0-9a-f]+)/i.exec((await result.textContent()) ?? "")?.[1] ?? "";

  const api = await waitFor(
    () =>
      events().find(
        (e) =>
          (e.event["tags"] as Record<string, string> | undefined)?.["request_id"] === reference,
      ),
    "the API's test error",
  );
  expect(api.path).toBe("/api/1/envelope/");
  expect(exceptionOf(api.event).type).toBe("MonitoringTestError");
  expect((api.event["user"] as { id?: string } | undefined)?.id).toMatch(/^[0-9a-f]{20}$/);

  await page.getByTestId("obs-web-test").click();
  await expect(page.getByTestId("obs-web-result")).toHaveText("Sent from the browser.");
  const web = await waitFor(
    () =>
      events().find(
        (e) =>
          (e.event["tags"] as Record<string, string> | undefined)?.["boundary"] === "console-test",
      ),
    "the web's test error",
  );
  expect(web.path).toBe("/api/2/envelope/");
  // under the web project's real DSN, which only the server holds: the page was given a stand-in
  const forwarded = received().find((r) => r.path === "/api/2/envelope/");
  expect(String(forwarded?.header["dsn"])).toContain("webkey@");
  const client = (await (await page.request.get("/api/v1/monitoring/client")).json()) as {
    dsn: string;
  };
  expect(client.dsn).not.toContain("webkey");
  const tags = web.event["tags"] as Record<string, string>;
  expect(tags["viewport"]).toBe("1440");
  expect(tags["display"]).toBe("browser");
  expect(String(web.event["release"])).toMatch(/^predigol-web@/);
  expect((web.event["user"] as { id?: string } | undefined)?.id).toBe(
    (api.event["user"] as { id?: string } | undefined)?.id,
  );

  const raw = readFileSync(SINK as string, "utf-8");
  for (const secret of [
    credentials("admin").email,
    credentials("admin").password,
    await sessionCookie(page),
  ]) {
    expect(raw).not.toContain(secret);
  }
});

test("an error the page throws with personal data in it arrives without it", async ({ page }) => {
  const email = "ana.perez" + "@example.com";
  const token = "Zk3pQ9mX_2vLr8TnY4wB7cHs1uJd6Ef0" + "Ga5KoPiRqWe";
  await page.goto("/home");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(1500); // the SDK is switched on after the page settles
  await page.evaluate(
    ([e, t]) => {
      setTimeout(() => {
        throw new Error(`lookup failed for ${e} with token ${t}`);
      }, 0);
    },
    [email, token],
  );
  const found = await waitFor(
    () => events().find((x) => (exceptionOf(x.event).value ?? "").startsWith("lookup failed for")),
    "the page's error",
  );
  expect(exceptionOf(found.event).value).toBe("lookup failed for <email> with token <token>");
  const raw = readFileSync(SINK as string, "utf-8");
  expect(raw).not.toContain(email);
  expect(raw).not.toContain(token);
});
