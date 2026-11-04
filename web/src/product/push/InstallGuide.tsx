/**
 * The guided install (plan UX, B7 and section 35: «InstallGuide: pasos para iPhone, porque iOS no tiene aviso de
 * instalación, y beforeinstallprompt en Android; se ofrece en contexto (al activar avisos), nunca al abrir»).
 *
 * On an iPhone or iPad the notices need the installed app (iOS 16.4 or later), so the steps say how to install it and
 * that the notices are turned on from the app afterwards. Where the browser offered its own install prompt (Chrome or
 * Edge on Android or at a desk), one button shows it. Anywhere else, the basic steps of «Más».
 */
import { useState } from "react";
import { Download, Share, SquarePlus, Smartphone } from "lucide-react";
import { t } from "@/lib/i18n";
import { installPlatform, promptInstall, type InstallPlatform } from "@/lib/pwa";
import { useInstallPrompt } from "./useInstallPrompt";

export function InstallGuide({
  platform = installPlatform(),
  forNotices = true,
}: {
  platform?: InstallPlatform;
  /** Shown because the reader wants notices (on an iPhone they need the app): the steps end there. */
  forNotices?: boolean;
}) {
  const canPrompt = useInstallPrompt();
  const [outcome, setOutcome] = useState<"accepted" | "dismissed" | "unavailable" | null>(null);

  if (platform === "ios") {
    return (
      <div className="space-y-2" data-testid="install-guide" data-platform="ios">
        <p className="text-sm">{t(forNotices ? "push.install.iosWhy" : "push.install.iosIntro")}</p>
        <ol className="space-y-2 text-sm">
          <li className="flex items-start gap-2">
            <Share aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>{t("push.install.iosStep1")}</span>
          </li>
          <li className="flex items-start gap-2">
            <SquarePlus aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>{t("push.install.iosStep2")}</span>
          </li>
          <li className="flex items-start gap-2">
            <Smartphone aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>{t(forNotices ? "push.install.iosStep3Notices" : "push.install.iosStep3")}</span>
          </li>
        </ol>
        <p className="text-caption text-muted-foreground">{t("push.install.iosVersion")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="install-guide" data-platform={platform}>
      <p className="text-sm">{t("push.install.otherIntro")}</p>
      {canPrompt ? (
        <button
          type="button"
          onClick={() => void promptInstall().then(setOutcome)}
          data-testid="install-prompt"
          className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-primary/45 bg-primary/10 px-4 text-sm font-semibold text-primary transition-colors hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Download aria-hidden className="h-4 w-4" />
          {t("push.install.button")}
        </button>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t(platform === "android" ? "nav.install.android" : "nav.install.other")}
        </p>
      )}
      {outcome === "accepted" ? (
        <p role="status" className="text-caption text-positive">
          {t("push.install.accepted")}
        </p>
      ) : null}
    </div>
  );
}
