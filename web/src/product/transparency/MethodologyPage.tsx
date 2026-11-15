/**
 * Metodología (plan maestro UX/UI 2026, decision 10; sheet T06): how PrediGol decides a pick, how its numbers are read and
 * which definitions are in force - on a page of its own. Every text is one that already existed in «Cómo le va a
 * PrediGol» (its blocks «Cómo se decide», «Cómo leer probabilidades y cuotas» and «Definiciones vigentes», which stay
 * there too): nothing is written anew. It is seen under the same rule as that page.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { HowToReadBlock } from "./Reading";
import { DefinitionsBlock, HowBlock } from "./TransparencyPage";

export function MethodologyPage() {
  const auth = useAuth();
  const preview = auth.showAdmin ? "shadow" : undefined;
  const q = useQuery(live.transparency(preview));
  const data = q.data?.status === "ok" ? q.data.data : null;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="methodology-page">
      <div>
        <Link
          to="/transparency"
          className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft aria-hidden className="h-4 w-4" />
          {t("transparency.page.title")}
        </Link>
      </div>
      <PageTitle
        title={t("transparency.methodology.title")}
        subtitle={t("transparency.methodology.subtitle")}
      />
      {q.isPending ? (
        <SkeletonCards count={3} />
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : !data ? (
        <Card>
          <EmptyState title={t("transparency.page.notAvailable")} />
        </Card>
      ) : (
        <>
          <HowBlock />
          <HowToReadBlock />
          <DefinitionsBlock data={data} />
        </>
      )}
    </div>
  );
}
