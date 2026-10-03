import { PageTitle } from "@/product/shared/States";
import { t } from "@/lib/i18n";

export function HomePage() {
  return <PageTitle title={t("nav.home")} />;
}
