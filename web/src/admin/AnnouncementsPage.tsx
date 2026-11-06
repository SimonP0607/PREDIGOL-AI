/**
 * The owner's communiqués (closing plan 4.3): a closed set of kinds - maintenance, incident, update and general notice
 * (there is no «promotion») - written in both languages, previewed destination by destination, and published only with the
 * code of the preview and the typed word PUBLICAR. A day holds a few; a published one is retracted, never deleted, and every
 * step is in the record. Nothing here reads the models or the picks: it is the owner's own words.
 */
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Loader2, Megaphone, Plus, Send, Undo2 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type {
  Announcement,
  AnnouncementPreview,
  AnnouncementPublished,
} from "@/lib/api/v1/types_announcements";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import {
  BODY_MAX,
  CRITICAL_KINDS,
  KINDS,
  TITLE_MAX,
  emptyForm,
  fromAnnouncement,
  phraseOk,
  problem,
  toBody,
  withKind,
  type Form,
} from "./announcements";

const KEY = ["admin", "announcements"] as const;
const FIELD = "w-full rounded-md border border-border-strong bg-background px-3 py-2 text-sm";
const BUTTON =
  "inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-medium hover:bg-elevated disabled:opacity-50";
const PRIMARY =
  "inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
    </label>
  );
}

function Check({
  label,
  checked,
  disabled,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (on: boolean) => void;
  testId: string;
}) {
  return (
    <label className={cn("flex min-h-11 items-center gap-2 text-sm", disabled && "opacity-50")}>
      <input
        type="checkbox"
        data-testid={testId}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4"
      />
      {label}
    </label>
  );
}

function Counter({ value, max }: { value: string; max: number }) {
  const n = value.trim().length;
  return (
    <span className={cn("text-xs", n > max ? "text-negative" : "text-muted-foreground")}>
      {t("notices.admin.counter", { n, max })}
    </span>
  );
}

function Editor({
  initial,
  telegramOn,
  saving,
  error,
  onSave,
  onCancel,
}: {
  initial: Form;
  telegramOn: boolean;
  saving: boolean;
  error: string | null;
  onSave: (form: Form) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(initial);
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm({ ...form, [key]: value });
  const wrong = problem(form);
  const canCritical = CRITICAL_KINDS.includes(form.kind);
  return (
    <form
      className="space-y-3 rounded-xl border border-border bg-card p-4"
      data-testid="announcement-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!wrong) onSave(form);
      }}
    >
      <Field label={t("notices.admin.fields.kind")}>
        <select
          data-testid="announcement-kind"
          className={FIELD}
          value={form.kind}
          onChange={(e) => setForm(withKind(form, e.target.value as Form["kind"]))}
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`notices.kind.${k}`)}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("notices.admin.fields.titleEs")}>
          <input
            data-testid="announcement-title-es"
            className={FIELD}
            maxLength={TITLE_MAX + 20}
            value={form.title_es}
            onChange={(e) => set("title_es", e.target.value)}
          />
          <Counter value={form.title_es} max={TITLE_MAX} />
        </Field>
        <Field label={t("notices.admin.fields.titleEn")}>
          <input
            data-testid="announcement-title-en"
            className={FIELD}
            maxLength={TITLE_MAX + 20}
            value={form.title_en}
            onChange={(e) => set("title_en", e.target.value)}
          />
          <Counter value={form.title_en} max={TITLE_MAX} />
        </Field>
        <Field label={t("notices.admin.fields.bodyEs")}>
          <textarea
            data-testid="announcement-body-es"
            className={cn(FIELD, "min-h-24")}
            value={form.body_es}
            onChange={(e) => set("body_es", e.target.value)}
          />
          <Counter value={form.body_es} max={BODY_MAX} />
        </Field>
        <Field label={t("notices.admin.fields.bodyEn")}>
          <textarea
            data-testid="announcement-body-en"
            className={cn(FIELD, "min-h-24")}
            value={form.body_en}
            onChange={(e) => set("body_en", e.target.value)}
          />
          <Counter value={form.body_en} max={BODY_MAX} />
        </Field>
        <Field label={t("notices.admin.fields.starts")}>
          <input
            type="datetime-local"
            data-testid="announcement-starts"
            className={FIELD}
            value={form.starts}
            onChange={(e) => set("starts", e.target.value)}
          />
        </Field>
        <Field label={t("notices.admin.fields.ends")}>
          <input
            type="datetime-local"
            data-testid="announcement-ends"
            className={FIELD}
            value={form.ends}
            onChange={(e) => set("ends", e.target.value)}
          />
        </Field>
      </div>
      <fieldset className="space-y-0.5">
        <legend className="text-sm font-medium">{t("notices.admin.fields.destinations")}</legend>
        <Check
          testId="announcement-to-banner"
          label={t("notices.admin.dest.banner")}
          checked={form.to_banner}
          onChange={(on) => set("to_banner", on)}
        />
        <Check
          testId="announcement-to-updates"
          label={t("notices.admin.dest.updates")}
          checked={form.to_updates}
          disabled={form.kind !== "update"}
          onChange={(on) => set("to_updates", on)}
        />
        <Check
          testId="announcement-to-telegram"
          label={t(telegramOn ? "notices.admin.dest.telegram" : "notices.admin.dest.telegramOff")}
          checked={form.to_telegram}
          onChange={(on) => set("to_telegram", on)}
        />
        <Check
          testId="announcement-critical"
          label={t("notices.admin.fields.critical")}
          checked={form.critical}
          disabled={!canCritical}
          onChange={(on) => setForm({ ...form, critical: on, to_email: on && form.to_email })}
        />
        <Check
          testId="announcement-to-email"
          label={t("notices.admin.dest.email")}
          checked={form.to_email}
          disabled={!form.critical}
          onChange={(on) => set("to_email", on)}
        />
      </fieldset>
      {wrong ? (
        <p className="text-sm text-warning" data-testid="announcement-problem">
          {t(`notices.admin.problem.${wrong}`)}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          data-testid="announcement-save"
          disabled={saving || wrong !== null}
          className={PRIMARY}
        >
          {saving ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("notices.admin.save")}
        </button>
        <button type="button" onClick={onCancel} className={BUTTON}>
          {t("notices.admin.cancel")}
        </button>
      </div>
    </form>
  );
}

function PreviewPanel({
  preview,
  onDone,
  onClose,
}: {
  preview: AnnouncementPreview;
  onDone: (done: AnnouncementPublished) => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const d = preview.destinations;
  const publish = useMutation({
    mutationFn: () =>
      v1.publishAnnouncement(preview.id, { code: preview.code, phrase: typed.trim() }),
    onSuccess: onDone,
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <div
      className="space-y-3 rounded-xl border border-gold/45 bg-gold-soft/40 p-4"
      data-testid="announcement-preview"
    >
      <h3 className="font-display text-base font-semibold">{t("notices.admin.previewTitle")}</h3>
      <ul className="space-y-1 text-sm">
        {d.banner ? (
          <li>
            {t("notices.admin.previewBanner", {
              from: formatDateTime(d.banner.from),
              until: formatDateTime(d.banner.until),
            })}
          </li>
        ) : null}
        {d.updates ? <li>{t("notices.admin.previewUpdates", { title: d.updates.es })}</li> : null}
        {d.telegram ? (
          <li>
            {d.telegram.configured
              ? t("notices.admin.previewTelegram", { title: d.telegram.title })
              : t("notices.admin.previewTelegramOff")}
          </li>
        ) : null}
        {d.email ? <li>{t("notices.admin.previewEmail", { n: d.email.recipients })}</li> : null}
      </ul>
      <p className="text-xs text-muted-foreground">
        {t("notices.admin.today", { n: preview.published_today, max: preview.daily_cap })}{" "}
        {t("notices.admin.expires", { time: formatDateTime(preview.expires_at) })}
      </p>
      <Field label={t("notices.admin.confirmLabel")}>
        <input
          data-testid="announcement-phrase"
          className={FIELD}
          autoComplete="off"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
        />
      </Field>
      {error ? (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          data-testid="announcement-publish"
          disabled={!phraseOk(typed) || publish.isPending}
          onClick={() => publish.mutate()}
          className={PRIMARY}
        >
          {publish.isPending ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Send aria-hidden className="h-4 w-4" />
          )}
          {t("notices.admin.publish")}
        </button>
        <button type="button" onClick={onClose} className={BUTTON}>
          {t("notices.admin.cancel")}
        </button>
      </div>
    </div>
  );
}

function LogList({ id }: { id: number }) {
  const q = useQuery({ queryKey: [...KEY, "log", id], queryFn: () => v1.announcementLog(id) });
  if (q.isPending) return <Loader2 aria-hidden className="h-4 w-4 animate-spin" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <ol
      className="space-y-0.5 text-xs text-muted-foreground"
      data-testid={`announcement-log-${id}`}
    >
      {q.data.map((line, i) => (
        <li key={i}>
          {formatDateTime(line.at)} · {t(`notices.admin.action.${line.action}`)}
        </li>
      ))}
    </ol>
  );
}

function Row({
  item,
  onEdit,
  onPreview,
  onRetract,
  busy,
}: {
  item: Announcement;
  onEdit: () => void;
  onPreview: () => void;
  onRetract: () => void;
  busy: boolean;
}) {
  const [log, setLog] = useState(false);
  return (
    <li
      className="space-y-2 rounded-md border border-border p-3"
      data-testid={`announcement-${item.id}`}
      data-status={item.status}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-medium">{item.title_es}</p>
          <p className="text-xs text-muted-foreground">
            {t(`notices.kind.${item.kind}`)} · {t(`notices.admin.status.${item.status}`)} ·{" "}
            {formatDateTime(item.starts_at)} → {formatDateTime(item.ends_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {item.status === "draft" ? (
            <>
              <button
                type="button"
                className={BUTTON}
                onClick={onEdit}
                data-testid="announcement-edit"
              >
                {t("notices.admin.edit")}
              </button>
              <button
                type="button"
                className={PRIMARY}
                disabled={busy}
                onClick={onPreview}
                data-testid="announcement-preview-open"
              >
                {t("notices.admin.preview")}
              </button>
            </>
          ) : null}
          {item.status === "published" ? (
            <button
              type="button"
              className={BUTTON}
              disabled={busy}
              onClick={onRetract}
              data-testid="announcement-retract"
            >
              <Undo2 aria-hidden className="h-4 w-4" />
              {t("notices.admin.retract")}
            </button>
          ) : null}
          <button type="button" className={BUTTON} onClick={() => setLog(!log)}>
            <History aria-hidden className="h-4 w-4" />
            {log ? t("notices.admin.hideLog") : t("notices.admin.log")}
          </button>
        </div>
      </div>
      {log ? <LogList id={item.id} /> : null}
    </li>
  );
}

export function AnnouncementsPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: KEY, queryFn: v1.announcements });
  const [editing, setEditing] = useState<{ id: number | null; form: Form } | null>(null);
  const [preview, setPreview] = useState<AnnouncementPreview | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: KEY });
  const save = useMutation({
    mutationFn: ({ id, form }: { id: number | null; form: Form }) =>
      id === null ? v1.createAnnouncement(toBody(form)) : v1.editAnnouncement(id, toBody(form)),
    onSuccess: () => {
      setEditing(null);
      setError(null);
      setNotice(t("notices.admin.saved"));
      void refresh();
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const ask = useMutation({
    mutationFn: (id: number) => v1.previewAnnouncement(id),
    onSuccess: (p) => {
      setPreview(p);
      setError(null);
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const retract = useMutation({
    mutationFn: (id: number) => v1.retractAnnouncement(id),
    onSuccess: () => {
      setNotice(t("notices.admin.retracted"));
      void refresh();
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const data = list.data;
  return (
    <div className="space-y-4" data-testid="announcements-admin">
      <PageHeader
        title={t("notices.admin.title")}
        description={t("notices.admin.description")}
        actions={<Megaphone aria-hidden className="h-5 w-5 text-gold" />}
      />
      {list.isPending ? <SkeletonCards count={2} /> : null}
      {list.isError ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : null}
      {data ? (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground" data-testid="announcements-state">
              {t("notices.admin.today", { n: data.published_today, max: data.daily_cap })}{" "}
              {t("notices.admin.telegramState", {
                state: t(
                  data.telegram_configured
                    ? "notices.admin.telegramOn"
                    : "notices.admin.telegramNo",
                ),
              })}
            </p>
            <button
              type="button"
              className={PRIMARY}
              data-testid="announcement-new"
              onClick={() => {
                setPreview(null);
                setNotice(null);
                setEditing({ id: null, form: emptyForm() });
              }}
            >
              <Plus aria-hidden className="h-4 w-4" />
              {t("notices.admin.new")}
            </button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{t("notices.admin.never")}</p>
        </Card>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-positive" data-testid="announcements-notice">
          {notice}
        </p>
      ) : null}
      {error && !editing && !preview ? (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      ) : null}
      {editing && data ? (
        <Editor
          initial={editing.form}
          telegramOn={data.telegram_configured}
          saving={save.isPending}
          error={error}
          onSave={(form) => save.mutate({ id: editing.id, form })}
          onCancel={() => {
            setEditing(null);
            setError(null);
          }}
        />
      ) : null}
      {preview ? (
        <PreviewPanel
          preview={preview}
          onClose={() => setPreview(null)}
          onDone={(done) => {
            setPreview(null);
            setNotice(
              t("notices.admin.published", {
                emails: done.emails_queued,
                telegram: t(`notices.admin.telegram.${done.telegram}`),
              }),
            );
            void refresh();
          }}
        />
      ) : null}
      {data && data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("notices.admin.empty")}</p>
      ) : null}
      {data && data.items.length > 0 ? (
        <ul className="space-y-2" data-testid="announcements-list">
          {data.items.map((item) => (
            <Row
              key={item.id}
              item={item}
              busy={ask.isPending || retract.isPending}
              onEdit={() => {
                setPreview(null);
                setEditing({ id: item.id, form: fromAnnouncement(item) });
              }}
              onPreview={() => {
                setEditing(null);
                ask.mutate(item.id);
              }}
              onRetract={() => retract.mutate(item.id)}
            />
          ))}
        </ul>
      ) : null}
    </div>
  );
}
