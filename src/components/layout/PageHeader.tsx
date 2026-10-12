import { Link, type LinkProps } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

export function PageHeader({
  breadcrumb,
  title,
  description,
  actions,
  className,
}: {
  breadcrumb?: Array<{ label: string; to?: LinkProps["to"] }> | undefined;
  title: string;
  description?: string | undefined;
  actions?: React.ReactNode | undefined;
  className?: string | undefined;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {breadcrumb?.length ? (
          <nav
            aria-label={t("admin.ui.breadcrumb")}
            className="mb-1.5 flex items-center gap-1.5 text-caption"
          >
            {breadcrumb.map((c, i) => (
              <span key={c.label} className="flex items-center gap-1.5">
                {i > 0 ? <span className="text-subtle-foreground">/</span> : null}
                {c.to ? (
                  <Link to={c.to} className="text-muted-foreground hover:text-primary">
                    {c.label}
                  </Link>
                ) : (
                  <span className="text-subtle-foreground">{c.label}</span>
                )}
              </span>
            ))}
          </nav>
        ) : null}
        <h1 className="text-display">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}
