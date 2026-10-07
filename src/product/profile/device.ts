import { t } from "@/lib/i18n";

/** "Chrome on Windows" from a user agent, without a library: enough to recognise one's own devices. */
export function deviceLabel(ua: string | null): string {
  if (!ua) return t("profile.securityPanel.unknownDevice");
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\//.test(ua)
      ? "Opera"
      : /Firefox\//.test(ua)
        ? "Firefox"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Safari\//.test(ua)
            ? "Safari"
            : null;
  const os = /iPhone|iPad/.test(ua)
    ? "iOS"
    : /Android/.test(ua)
      ? "Android"
      : /Windows/.test(ua)
        ? "Windows"
        : /Mac OS X/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : null;
  if (browser && os) return t("profile.securityPanel.browserOn", { browser, os });
  return browser ?? os ?? ua.slice(0, 40);
}
