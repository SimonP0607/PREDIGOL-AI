/**
 * What the views of the shadow share (plan IA, phase 3): the empty state when the shadow is off or has written nothing - it names the owner's three
 * words and says which of them is missing -, and the small pieces of a verdict side by side.
 */
import { t, translateOr } from "@/lib/i18n";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import type { ShadowSwitches } from "@/lib/api/v1/types_ai_shadow";
import { Note } from "./AiBits";
import { decisionLabel, decisionTone } from "./aiModel";

/**
 * "La sombra está apagada" with the switches' names, or - when the words are all on - that it has not written anything yet. It never shows a
 * value of an environment variable other than the three words of the shadow (engines, sample and agents), which are not secrets.
 */
export function ShadowOffNotice({
  switches,
  testId = "shadow-off",
}: {
  switches: ShadowSwitches;
  testId?: string;
}) {
  const off = !switches.orchestrate;
  return (
    <div
      role="status"
      data-testid={testId}
      data-off={off ? "true" : "false"}
      className="space-y-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs"
    >
      <div className="font-medium">{t(off ? "ai.shadowOff.title" : "ai.shadowOff.titleOn")}</div>
      <Note>{t(off ? "ai.shadowOff.body" : "ai.shadowOff.bodyOn")}</Note>
      {switches.mode === "off" ? <Note>{t("ai.shadowOff.modeOff")}</Note> : null}
      <ul className="space-y-1" data-testid={`${testId}-words`}>
        {switches.words.map((w) => (
          <li key={w.name} className="flex flex-wrap items-center gap-2">
            <code className="numeric text-caption">{w.name}</code>
            <span className="numeric text-muted-foreground">{w.value === "" ? "—" : w.value}</span>
            <StatusBadge tone={w.on ? "positive" : "warning"} dot={false}>
              {t(w.on ? "ai.shadowOff.on" : "ai.shadowOff.missing")}
            </StatusBadge>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A decision of the Council (or of a reviewer) as a badge; a cell with no verdict is a dash. */
export function VerdictBadge({ decision }: { decision: string | null }) {
  if (decision === null) return <span className="text-muted-foreground">—</span>;
  return (
    <StatusBadge tone={decisionTone(decision)} dot={false}>
      {decisionLabel(decision)}
    </StatusBadge>
  );
}

/** A list of codes as small badges, or nothing. Codes are shown as the server sent them; one with words is translated. */
export function Codes({ codes, prefix }: { codes: readonly string[]; prefix?: string }) {
  if (codes.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {codes.map((c) => (
        <StatusBadge key={c} tone="neutral" dot={false}>
          {prefix ? translateOr(`${prefix}.${c}`, c) : c}
        </StatusBadge>
      ))}
    </span>
  );
}

/** Typed references (E:12, P:path, A:label) in a row: monospaced, never a link. */
export function Refs({ refs }: { refs: readonly string[] }) {
  if (refs.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="numeric inline-flex flex-wrap gap-x-2 text-caption text-muted-foreground">
      {refs.map((r) => (
        <span key={r}>{r}</span>
      ))}
    </span>
  );
}
