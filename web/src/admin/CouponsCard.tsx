/**
 * The coupons of the membership, in the owner's console (UX-005): the list with who holds each one and how many payments
 * used it, the form to create one whenever he wants, and the button that turns one off (for good: it is never deleted).
 * Nothing here charges anything; a coupon is only a percentage the console proposes when he records a payment.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Ticket } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { AdminCoupon } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, ErrorState, errorMessage } from "@/product/shared/States";
import { couponState, lastMomentOf, type CouponState } from "./coupons";

const field =
  "mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none sm:text-sm";
const KEY = ["v1", "admin", "coupons"] as const;
const TONE: Readonly<Record<CouponState, string>> = {
  active: "border-positive/40 bg-positive-soft text-positive",
  disabled: "border-border-strong text-muted-foreground",
  expired: "border-border-strong text-muted-foreground",
  full: "border-warning/40 bg-warning-soft text-warning",
};

function CreateForm({ onDone }: { onDone: (message: string) => void }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [percent, setPercent] = useState("");
  const [note, setNote] = useState("");
  const [until, setUntil] = useState("");
  const [places, setPlaces] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      v1.createCoupon({
        code: code.trim(),
        percent: Number(percent),
        note: note.trim() || null,
        valid_until: lastMomentOf(until),
        max_redemptions: places.trim() ? Number(places) : null,
      }),
    onSuccess: (c) => {
      setError(null);
      setCode("");
      setPercent("");
      setNote("");
      setUntil("");
      setPlaces("");
      void qc.invalidateQueries({ queryKey: KEY });
      onDone(t("admin.coupons.created", { code: c.code }));
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const ready = code.trim().length >= 3 && Number(percent) >= 1 && Number(percent) <= 100;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || create.isPending) return;
    create.mutate();
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2" data-testid="coupon-create-form">
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.coupons.code")}</span>
        <input
          value={code}
          maxLength={32}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          onChange={(e) => setCode(e.target.value)}
          className={cn(field, "numeric uppercase")}
          data-testid="coupon-new-code"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.coupons.percent")}</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={100}
          value={percent}
          onChange={(e) => setPercent(e.target.value)}
          className={cn(field, "numeric")}
          data-testid="coupon-new-percent"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.coupons.validUntil")}</span>
        <input
          type="date"
          value={until}
          onChange={(e) => setUntil(e.target.value)}
          className={field}
          data-testid="coupon-new-until"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.coupons.maxRedemptions")}</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={100000}
          value={places}
          onChange={(e) => setPlaces(e.target.value)}
          className={cn(field, "numeric")}
          data-testid="coupon-new-places"
        />
      </label>
      <label className="block sm:col-span-2">
        <span className="text-xs text-muted-foreground">{t("admin.coupons.note")}</span>
        <input
          value={note}
          maxLength={120}
          autoComplete="off"
          onChange={(e) => setNote(e.target.value)}
          className={field}
          data-testid="coupon-new-note"
        />
      </label>
      {error ? (
        <p
          role="alert"
          className="text-xs text-negative sm:col-span-2"
          data-testid="coupon-new-error"
        >
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={!ready || create.isPending}
          className="tap-y relative inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          data-testid="coupon-new-submit"
        >
          {create.isPending ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Plus aria-hidden className="h-4 w-4" />
          )}
          {t("admin.coupons.create")}
        </button>
      </div>
    </form>
  );
}

function CouponRow({ coupon }: { coupon: AdminCoupon }) {
  const qc = useQueryClient();
  const [asking, setAsking] = useState(false);
  const state = couponState(coupon);
  const off = useMutation({
    mutationFn: () => v1.disableCoupon(coupon.id),
    onSuccess: () => {
      setAsking(false);
      void qc.invalidateQueries({ queryKey: KEY });
    },
  });
  return (
    <li
      className="flex flex-wrap items-start justify-between gap-2 rounded-md border border-border p-3"
      data-testid={`coupon-${coupon.code}`}
      data-state={state}
    >
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">
          <Ticket aria-hidden className="h-4 w-4 text-muted-foreground" />
          <span className="numeric">{coupon.code}</span>
          <span className="numeric">
            {t("admin.coupons.percentValue", { percent: coupon.percent })}
          </span>
          <span
            className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", TONE[state])}
            data-testid="coupon-state"
          >
            {t(`admin.coupons.state.${state}`)}
          </span>
        </p>
        {coupon.note ? <p className="text-xs text-muted-foreground">{coupon.note}</p> : null}
        <p className="numeric text-caption text-muted-foreground">
          {t("admin.coupons.holders")}: {coupon.redemptions}
          {coupon.max_redemptions !== null ? ` / ${coupon.max_redemptions}` : ""} ·{" "}
          {t("admin.coupons.used")}: {coupon.used} ·{" "}
          {coupon.valid_until ? formatDateYear(coupon.valid_until) : t("admin.coupons.noDate")}
        </p>
      </div>
      {!coupon.disabled_at ? (
        asking ? (
          <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="coupon-confirm">
            <span>{t("admin.coupons.confirmDisable", { code: coupon.code })}</span>
            <button
              type="button"
              onClick={() => off.mutate()}
              disabled={off.isPending}
              className="tap-y relative rounded-md border border-negative/50 px-2 py-1 font-semibold text-negative"
              data-testid="coupon-disable-yes"
            >
              {t("admin.coupons.yes")}
            </button>
            <button
              type="button"
              onClick={() => setAsking(false)}
              className="tap-y relative rounded-md border border-border-strong px-2 py-1"
            >
              {t("admin.coupons.no")}
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="tap-y relative rounded-md border border-border-strong px-2 py-1 text-xs font-medium hover:bg-elevated"
            data-testid="coupon-disable"
          >
            {t("admin.coupons.disable")}
          </button>
        )
      ) : null}
      {off.isError ? (
        <p role="alert" className="w-full text-xs text-negative">
          {errorMessage(off.error)}
        </p>
      ) : null}
    </li>
  );
}

export function CouponsCard() {
  const q = useQuery({ queryKey: KEY, queryFn: v1.adminCoupons });
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <Card className="space-y-3 p-4" data-testid="coupons-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h2 className="text-base font-semibold">{t("admin.coupons.title")}</h2>
          <p className="max-w-3xl text-xs text-muted-foreground">
            {t("admin.coupons.description")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setNotice(null);
            setOpen((v) => !v);
          }}
          className="tap-y relative inline-flex h-9 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-semibold hover:bg-elevated"
          data-testid="coupon-open-form"
        >
          <Plus aria-hidden className="h-4 w-4" />
          {t("admin.coupons.create")}
        </button>
      </div>
      {notice ? (
        <p
          role="status"
          className="rounded-md border border-positive/40 bg-positive/10 px-3 py-2 text-sm text-positive"
          data-testid="coupon-notice"
        >
          {notice}
        </p>
      ) : null}
      {open ? (
        <CreateForm
          onDone={(message) => {
            setOpen(false);
            setNotice(message);
          }}
        />
      ) : null}
      {q.isPending ? (
        <Loader2 aria-hidden className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data.coupons.length ? (
        <ul className="space-y-2" data-testid="coupon-list">
          {q.data.coupons.map((c) => (
            <CouponRow key={c.id} coupon={c} />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="coupon-empty">
          {t("admin.coupons.empty")}
        </p>
      )}
    </Card>
  );
}
