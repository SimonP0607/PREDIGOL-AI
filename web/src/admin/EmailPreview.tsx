/**
 * The console's e-mail preview (plan de correcciones UX, AP-M02): the exact HTML a template leaves with, in a sandboxed frame
 * (no script, no forms, no same-origin access: the e-mail's own markup cannot reach the console), at phone or desktop width, in
 * Spanish or English - and «Enviarme una prueba», which queues it for the administrator's own account only.
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Monitor, Send, Smartphone } from "lucide-react";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { cn } from "@/lib/utils";
import { Card, ErrorState } from "@/product/shared/States";
import { t } from "./emailText";
import { PREVIEW_TEMPLATES, templateName } from "./messages";

type Locale = "es" | "en";
type Device = "phone" | "desktop";

const WIDTH: Readonly<Record<Device, number>> = { phone: 375, desktop: 640 };

/** The e-mail's HTML in an isolated frame. ``sandbox=""`` forbids scripts, forms, popups and the page's own origin. */
export function EmailFrame({
  html,
  title,
  device = "desktop",
}: {
  html: string;
  title: string;
  device?: Device;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-elevated/40 p-2">
      <iframe
        title={title}
        sandbox=""
        srcDoc={html}
        referrerPolicy="no-referrer"
        loading="lazy"
        data-testid="email-frame"
        data-device={device}
        style={{ width: WIDTH[device], maxWidth: "100%" }}
        className="mx-auto block h-[34rem] rounded bg-white"
      />
    </div>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: T;
  options: readonly { value: T; text: string; icon?: React.ReactNode }[];
  onChange: (v: T) => void;
  testId: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          data-testid={`${testId}-${o.value}`}
          className={cn(
            "tap-y relative inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs",
            value === o.value
              ? "border-primary bg-primary/10 text-primary"
              : "border-border-strong",
          )}
        >
          {o.icon}
          {o.text}
        </button>
      ))}
    </div>
  );
}

/** What the answer to «Enviarme una prueba» says, by what the API said. */
export function testMessage(error: unknown): string {
  if (error instanceof LiveApiError) {
    if (error.code === "test_limit") return t("emailpreview.limit");
    if (error.code === "test_unavailable") return t("emailpreview.notThisOne");
  }
  return t("emailpreview.failed");
}

export function EmailPreview() {
  const [template, setTemplate] = useState<string>(PREVIEW_TEMPLATES[0] ?? "welcome");
  const [locale, setLocale] = useState<Locale>("es");
  const [device, setDevice] = useState<Device>("phone");
  const q = useQuery({
    queryKey: ["admin", "messages", "template-preview", template, locale],
    queryFn: () => v1.previewTemplate({ template, locale }),
    staleTime: 60_000,
  });
  const test = useMutation({ mutationFn: () => v1.sendTemplateTest({ template, locale }) });
  const language = locale === "es" ? "español" : "English";
  return (
    <Card className="space-y-4 p-4" data-testid="email-preview">
      <div className="space-y-1">
        <h2 className="text-title">{t("emailpreview.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("emailpreview.intro")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          {t("emailpreview.template")}
          <select
            value={template}
            onChange={(e) => {
              setTemplate(e.target.value);
              test.reset();
            }}
            data-testid="email-template"
            className="min-h-11 rounded-md border border-border-strong bg-background px-2 text-sm text-foreground"
          >
            {PREVIEW_TEMPLATES.map((name) => (
              <option key={name} value={name}>
                {templateName(name)}
              </option>
            ))}
          </select>
        </label>
        <Choice<Locale>
          label={t("emailpreview.language")}
          value={locale}
          onChange={(v) => {
            setLocale(v);
            test.reset();
          }}
          testId="email-locale"
          options={[
            { value: "es", text: "ES" },
            { value: "en", text: "EN" },
          ]}
        />
        <Choice<Device>
          label={t("emailpreview.device")}
          value={device}
          onChange={setDevice}
          testId="email-device"
          options={[
            {
              value: "phone",
              text: t("emailpreview.phone"),
              icon: <Smartphone aria-hidden className="h-3.5 w-3.5" />,
            },
            {
              value: "desktop",
              text: t("emailpreview.desktop"),
              icon: <Monitor aria-hidden className="h-3.5 w-3.5" />,
            },
          ]}
        />
      </div>
      {q.isPending ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          {t("emailpreview.loading")}
        </p>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <div className="space-y-2">
          <p className="text-sm" data-testid="email-subject">
            <span className="text-muted-foreground">{t("emailpreview.subject")}: </span>
            <span className="font-semibold">{q.data.subject}</span>
          </p>
          <EmailFrame
            html={q.data.html}
            device={device}
            title={t("emailpreview.frame", { template: templateName(template), language })}
          />
          {q.data.link ? (
            <p className="break-all text-xs text-muted-foreground">
              {t("emailpreview.button", { link: q.data.link })}
            </p>
          ) : null}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending || q.isPending || q.isError}
          data-testid="email-send-test"
          className="tap-y relative inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {test.isPending ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Send aria-hidden className="h-4 w-4" />
          )}
          {test.isPending ? t("emailpreview.sending") : t("emailpreview.sendTest")}
        </button>
        <p className="text-caption text-muted-foreground">{t("emailpreview.limitNote")}</p>
      </div>
      <div aria-live="polite" data-testid="email-test-result">
        {test.isSuccess ? (
          <p className="text-sm text-positive">
            {test.data.queued
              ? t("emailpreview.queued", { language })
              : t("emailpreview.alreadyQueued")}
          </p>
        ) : test.isError ? (
          <p className="text-sm text-negative">{testMessage(test.error)}</p>
        ) : null}
      </div>
    </Card>
  );
}
