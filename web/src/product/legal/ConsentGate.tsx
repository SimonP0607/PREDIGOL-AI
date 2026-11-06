/**
 * The consent gate (plan UX, A4; plan de seguridad, section 23): before the product, the reader answers each purpose
 * on its own - the terms, the processing of their data, the +18 declaration and the reading of the risk notice - in
 * separate, unticked boxes with the exact sentence the server stores, and a link to the text it refers to. After a
 * material change of a text, only the purposes on that text come back, with what changed.
 *
 * Beside them, the usage statistics are an optional box, unticked, that never counts for opening the gate (plan de
 * cierre UX, 1.2): left as it is, it records nothing.
 *
 * The server decides (403 consent_required on every product route); this only asks. The reader can still sign out,
 * read the texts, and open their profile to take a copy of their data or ask for its deletion without accepting.
 */
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Loader2, LogOut, ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import type { ConsentKind, ConsentPurpose } from "@/lib/api/v1/types_customer";
import { t, useI18n } from "@/lib/i18n";
import { BrandLogo } from "@/components/brand/Brand";
import { Disclaimer } from "@/components/system/Disclaimer";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { Card, ErrorState, errorMessage } from "@/product/shared/States";
import { gateOptional } from "@/product/profile/consents";
import { legalPath } from "./links";
import { OptionalConsent } from "./OptionalConsent";

export function ConsentGate({
  due,
  source = "gate",
}: {
  due: readonly string[];
  /** activation: right after /activate (plan UX, A7) - the server keeps it only within the hour of the activation. */
  source?: "gate" | "activation";
}) {
  const auth = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { locale } = useI18n();
  const state = useQuery({
    queryKey: ["me", "consents", locale],
    queryFn: () => v1.myConsents(locale),
  });
  const [ticked, setTicked] = useState<ReadonlySet<ConsentKind>>(new Set());
  const [statistics, setStatistics] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const owed: ConsentPurpose[] = (state.data?.purposes ?? []).filter((p) =>
    (state.data?.due.length ? state.data.due : due).includes(p.kind),
  );
  const changed = owed.filter((p) => p.changes);
  const changedDocs = [...new Map(changed.map((p) => [p.document, p])).values()];
  const complete = owed.length > 0 && owed.every((p) => ticked.has(p.kind));
  const optional = gateOptional(state.data);

  function toggle(kind: ConsentKind, on: boolean) {
    setTicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(kind);
      else next.delete(kind);
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!complete || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await v1.decideConsents({
        decisions: [
          ...owed.map((p) => ({ kind: p.kind, granted: true, version: p.version })),
          // only when the reader ticked it: an unticked optional box is no decision at all
          ...(optional && statistics
            ? [{ kind: optional.kind, granted: true, version: optional.version }]
            : []),
        ],
        locale,
        source,
      });
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
      await qc.invalidateQueries({ queryKey: ["auth", "me"] });
    } catch (err) {
      if (err instanceof LiveApiError && err.code === "legal_text_changed") {
        setTicked(new Set());
        setStatistics(false);
        setFailure(t("legal.gate.textChanged"));
        await state.refetch();
      } else {
        setFailure(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-background" data-testid="consent-gate">
      <header className="safe-top border-b border-border">
        <div className="px-safe mx-auto flex h-14 max-w-3xl items-center gap-3">
          <BrandLogo size={30} tagline={t("common.tagline")} />
          <LanguageSwitch className="ml-auto" />
        </div>
      </header>
      <main className="px-safe mx-auto w-full max-w-3xl py-6">
        <Card className="space-y-4 p-5">
          <h1 className="flex items-center gap-2 font-display text-xl font-semibold">
            <ShieldCheck aria-hidden className="h-5 w-5 text-primary" />
            {t("legal.gate.title")}
          </h1>
          {state.isPending ? (
            <Loader2 aria-hidden className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : state.isError ? (
            <ErrorState error={state.error} onRetry={() => void state.refetch()} />
          ) : (
            <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
              {changedDocs.length ? (
                <div className="space-y-2" data-testid="consent-changes">
                  {changedDocs.map((p) => (
                    <p
                      key={p.document}
                      className="rounded-md border border-info/30 bg-info-soft px-3 py-2 text-sm"
                    >
                      {t("legal.gate.changed", {
                        document: t(`legal.doc.${p.document}`),
                        changes: p.changes ?? "",
                      })}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{t("legal.gate.intro")}</p>
              )}
              <fieldset className="space-y-3">
                <legend className="sr-only">{t("legal.gate.title")}</legend>
                {owed.map((p) => (
                  <div key={p.kind} className="rounded-md border border-border p-3">
                    {/* The whole row is the box's label: 44 px tall at least to a finger. */}
                    <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm leading-relaxed">
                      <input
                        type="checkbox"
                        name={p.kind}
                        data-testid={`consent-${p.kind}`}
                        checked={ticked.has(p.kind)}
                        onChange={(e) => toggle(p.kind, e.currentTarget.checked)}
                        className="mt-0.5 h-5 w-5 shrink-0 accent-primary"
                      />
                      <span>{p.statement}</span>
                    </label>
                    <a
                      href={legalPath(p.document)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="tap-y relative ml-8 inline-block text-xs text-primary underline-offset-2 hover:underline"
                    >
                      {t("legal.gate.read", { document: t(`legal.doc.${p.document}`) })}
                    </a>
                  </div>
                ))}
              </fieldset>
              {optional ? (
                <OptionalConsent purpose={optional} ticked={statistics} onToggle={setStatistics} />
              ) : null}
              {failure ? (
                <p role="alert" className="text-sm text-negative" data-testid="consent-error">
                  {failure}
                </p>
              ) : null}
              {!complete ? (
                <p className="text-xs text-muted-foreground">{t("legal.gate.allRequired")}</p>
              ) : null}
              <button
                type="submit"
                disabled={!complete || busy}
                data-testid="consent-submit"
                className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
                {busy ? t("legal.gate.submitting") : t("legal.gate.submit")}
              </button>
            </form>
          )}
        </Card>
        <div className="mt-4 flex flex-wrap gap-2">
          <a
            href="/profile"
            className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3 py-2 text-sm hover:bg-elevated"
            data-testid="consent-profile"
          >
            {t("legal.gate.profile")}
          </a>
          <button
            type="button"
            onClick={() => void auth.signOut().then(() => navigate({ to: "/login" }))}
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm hover:bg-elevated"
          >
            <LogOut aria-hidden className="h-4 w-4" />
            {t("legal.gate.signOut")}
          </button>
        </div>
      </main>
      <footer className="px-safe mx-auto max-w-3xl pb-[calc(2rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground">
        <Disclaimer />
      </footer>
    </div>
  );
}
