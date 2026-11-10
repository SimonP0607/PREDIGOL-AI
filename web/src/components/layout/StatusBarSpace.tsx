/**
 * The status bar of the installed iPhone app (mobile UX plan, UX-090). With a black-translucent status bar and
 * viewport-fit=cover the page runs under the clock, so whatever is drawn first at the top must start below it: a
 * notice above the top bar (the owner's «Viendo como usuario», the shadow preview) sat under the clock with its button.
 *
 * Two pieces, both 0 px tall in a browser (the insets are 0 there): a spacer in the page's flow that starts the page
 * below the status bar, and a fixed backdrop over the status bar that content scrolls under, as the top bar did with
 * its own padding. The top bar then sticks just below the status bar (`top-[env(safe-area-inset-top)]`), so it is the
 * same 56 px plus the inset as before and --app-header-h keeps meaning its bottom edge.
 */
import { cn } from "@/lib/utils";

export function StatusBarSpace({ className }: { className?: string | undefined }) {
  return (
    <>
      <div aria-hidden className="h-[env(safe-area-inset-top)]" data-testid="status-bar-spacer" />
      <div
        aria-hidden
        className={cn(
          "pointer-events-none fixed inset-x-0 top-0 z-40 h-[env(safe-area-inset-top)] bg-background/85 backdrop-blur",
          className,
        )}
      />
    </>
  );
}
