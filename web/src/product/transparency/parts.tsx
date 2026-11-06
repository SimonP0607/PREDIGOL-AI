/**
 * The pieces every block of «Cómo le va a PrediGol» is made of (plan UX, A12; plan de cierre UX, 1.5): the card with its title,
 * a note in small type, and a figure beside what it counts. Shared by the page and by its blocks that live apart.
 */
import { useId, type ReactNode } from "react";
import { Card } from "@/product/shared/States";

export function Block({
  id,
  title,
  subtitle,
  icon,
  children,
}: {
  id: string;
  title: string;
  subtitle?: string | undefined;
  icon: ReactNode;
  children: ReactNode;
}) {
  const titleId = useId();
  return (
    <Card className="p-4 sm:p-5" id={`transparency-${id}`}>
      <div
        aria-labelledby={titleId}
        data-testid={`transparency-${id}`}
        className="space-y-3"
        role="group"
      >
        <div>
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-base font-semibold tracking-tight sm:text-lg"
          >
            <span aria-hidden className="text-subtle-foreground">
              {icon}
            </span>
            {title}
          </h2>
          {subtitle ? <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p> : null}
        </div>
        {children}
      </div>
    </Card>
  );
}

export function Note({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="text-caption leading-snug text-subtle-foreground" data-testid={testId}>
      {children}
    </p>
  );
}

/** A figure and what it counts, together (plan: «la cifra y su n juntas»). */
export function Figure({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd className="numeric text-base font-semibold text-foreground" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}
