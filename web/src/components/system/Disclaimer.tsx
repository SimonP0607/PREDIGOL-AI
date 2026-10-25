/**
 * The notice on every screen - information and analysis, no guaranteed result, +18 - with the three legal texts it
 * refers to (plan UX, A4; plan de seguridad, section 23: the risk notice with its responsible-gaming link).
 */
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { legalPath } from "@/product/legal/links";

export function Disclaimer({ className }: { className?: string | undefined }) {
  const links = [
    { href: legalPath("terms"), label: t("legal.links.terms") },
    { href: legalPath("privacy"), label: t("legal.links.privacy") },
    { href: legalPath("responsible_gaming"), label: t("legal.links.responsibleGaming") },
  ];
  return (
    <div className={cn("space-y-1", className)} data-testid="disclaimer">
      <p>{t("common.disclaimer")}</p>
      <nav aria-label={t("legal.links.label")}>
        <ul className="flex flex-wrap items-center justify-center gap-x-1 gap-y-0.5">
          {links.map((l, i) => (
            <li key={l.href} className="flex items-center gap-x-1">
              {i > 0 ? <span aria-hidden>·</span> : null}
              <a
                href={l.href}
                className="tap-y relative underline-offset-2 hover:text-foreground hover:underline"
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
