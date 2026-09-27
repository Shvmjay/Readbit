"use client";

import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useT } from "@/lib/i18n-client";
import clsx from "clsx";

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-muted">
      <Loader2 className={clsx("h-4 w-4 animate-spin", className)} aria-hidden />
      <span className={label ? "" : "sr-only"}>{label ?? "Loading"}</span>
    </span>
  );
}

export function LoadingSkeleton({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={clsx("animate-pulse space-y-3", className)} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 rounded bg-line/70" style={{ width: `${90 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-12 text-center">
      {icon && <div className="mb-4 rounded-2xl bg-accent-soft p-3 text-accent">{icon}</div>}
      <h2 className="text-lg font-semibold">{title}</h2>
      {body && <div className="mt-2 max-w-md text-sm text-muted">{body}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function errorMessage(err: unknown, t: (k: string) => string): string {
  if (err instanceof ApiError) {
    const key = `errors.${err.code}`;
    const translated = t(key);
    // Prefer the server's specific, actionable message; fall back to a localized generic one.
    return err.message && err.status !== 0 ? err.message : translated !== key ? translated : t("errors.generic");
  }
  return t("errors.generic");
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useT();
  const retryable = error instanceof ApiError ? error.retryable : true;
  return (
    <div role="alert" className="card flex flex-col items-start gap-3 border-danger/30 p-5">
      <div className="flex items-center gap-2 font-medium text-danger">
        <AlertTriangle className="h-4 w-4" aria-hidden /> {t("common.error")}
      </div>
      <p className="text-sm text-ink">{errorMessage(error, t)}</p>
      <p className="text-xs text-muted">{t("common.workSafe")}</p>
      {onRetry && retryable && (
        <button className="btn-secondary" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function ProgressBar({ value, label, className }: { value: number; label: string; className?: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className={className}>
      <div role="progressbar" aria-label={label} aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}
        className="h-2 w-full overflow-hidden rounded-full bg-line/70">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}
