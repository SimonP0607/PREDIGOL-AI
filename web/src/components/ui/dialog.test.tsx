/// <reference types="bun" />
/**
 * A dialog fits what the screen shows (mobile UX plan, UX-096). Centred with no height limit, a tall dialog on a 320 px
 * phone or a phone held sideways (354 px) began 132 to 402 px above the screen's top: its title and close out of
 * reach. The bases of every dialog (Dialog and AlertDialog) now stop at the visible height, minus the safe areas of an
 * installed iPhone app, and scroll inside. Radix draws a dialog in a portal, which a server render leaves empty, so this
 * reads the class the base gives; the measured check is in the plan's record.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const base = (file: string) => readFileSync(join(import.meta.dir, file), "utf8");

describe("dialog bases", () => {
  for (const file of ["dialog.tsx", "alert-dialog.tsx"]) {
    test(`${file}: never taller nor wider than the visible screen, and scrolls inside`, () => {
      const src = base(file);
      expect(src).toContain(
        "max-h-[calc(100dvh-2rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))]",
      );
      expect(src).toContain(
        "w-[calc(100%-2rem-env(safe-area-inset-left)-env(safe-area-inset-right))]",
      );
      expect(src).toContain("overflow-y-auto");
      expect(src).not.toMatch(/grid w-full max-w-lg/);
    });
  }
});
