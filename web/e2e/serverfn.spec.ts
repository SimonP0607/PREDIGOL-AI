/**
 * R02 (security audit; phase A0 of the UX plan): a link to the server-function path is opened as a page and must
 * never come back as HTML built from the request. GHSA-qx66-fv34-fjm8 let a crafted link make a TanStack Start app
 * answer attacker HTML from its own origin; the framework is now past it, and src/lib/frameworkAdvisories.test.ts
 * keeps every copy of it in bun.lock at the fixed versions - that floor is the guard. This test is the visible side
 * of it: it opens such a link the way a browser does (a document navigation, no session) with a harmless marker in
 * the payload and checks that nothing of it reaches the page as markup. It carries no exploit: the marker is a bold
 * tag. The app defines no server function of its own; the path is the framework's. The server's smoke check after
 * a deploy makes the same request.
 */
import { expect, test } from "@playwright/test";

const MARK = "r02-probe";
const PAYLOAD = `<b id="${MARK}">${MARK}</b>`;

test("a document navigation to the server-function path never renders markup from its payload", async ({
  page,
}) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  const res = await page.goto(`/_serverFn/predigol-probe?payload=${encodeURIComponent(PAYLOAD)}`);
  expect(res, "the server answered").not.toBeNull();
  const type = res?.headers()["content-type"] ?? "";
  // Whatever the status, an HTML answer must not carry the payload's tag as markup.
  if (type.includes("text/html")) expect(await res?.text()).not.toContain(PAYLOAD);
  await expect(page.locator(`#${MARK}`)).toHaveCount(0);
  expect(dialogs).toEqual([]);
});
