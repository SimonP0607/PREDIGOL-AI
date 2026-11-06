/**
 * The box the gate offers apart from the ones it asks for (plan de cierre UX, 1.2): the usage statistics under a
 * pseudonym. Unticked, marked as optional, with the exact sentence the server stores and a link to the policy it is on.
 * It never counts for opening the gate: leaving it as it is records nothing.
 */
import type { ConsentPurpose } from "@/lib/api/v1/types_customer";
import { t } from "@/lib/i18n";
import { legalPath } from "./links";

export function OptionalConsent({
  purpose,
  ticked,
  onToggle,
}: {
  purpose: ConsentPurpose;
  ticked: boolean;
  onToggle: (on: boolean) => void;
}) {
  return (
    <div
      className="rounded-md border border-dashed border-border p-3"
      data-testid="consent-optional"
    >
      <p className="text-caption font-semibold uppercase tracking-wide text-subtle-foreground">
        {t("legal.gate.optional")}
      </p>
      {/* The whole row is the box's label: 44 px tall at least to a finger. */}
      <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm leading-relaxed">
        <input
          type="checkbox"
          name={purpose.kind}
          data-testid={`consent-${purpose.kind}`}
          checked={ticked}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 accent-primary"
        />
        <span>{purpose.statement}</span>
      </label>
      <p className="ml-8 text-xs text-muted-foreground">{t("legal.gate.optionalHelp")}</p>
      <a
        href={legalPath(purpose.document)}
        target="_blank"
        rel="noopener noreferrer"
        className="tap-y relative ml-8 inline-block text-xs text-primary underline-offset-2 hover:underline"
      >
        {t("legal.gate.read", { document: t(`legal.doc.${purpose.document}`) })}
      </a>
    </div>
  );
}
