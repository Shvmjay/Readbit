"use client";

import { AlertTriangle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import type { Book } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { api } from "@/lib/api";
import { ProgressBar } from "@/components/ui/States";

const STAGES = ["uploaded", "validating", "extracting", "structuring", "chunking", "indexing", "ready"] as const;

export function ProcessingStatus({ book, compact = false }: { book: Book; compact?: boolean }) {
  const { t } = useT();
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: () => api.post(`/books/${book.id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["book", book.id] }),
  });
  const status = book.processing_status;
  const job = book.processing_job;
  if (compact) {
    return (
      <span className={clsx("inline-flex items-center gap-1", status === "failed" ? "text-danger" : "text-accent")} data-testid="processing-status">
        {status === "failed" ? <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> : <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
        {t(`processing.${status}`)}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <div role="alert" className="card border-danger/30 p-5" data-testid="processing-failed">
        <p className="flex items-center gap-2 font-semibold text-danger"><AlertTriangle className="h-5 w-5" aria-hidden />{t("processing.failedTitle")}</p>
        <p className="mt-2 text-sm">{job?.error?.message}</p>
        <button className="btn-secondary mt-4" onClick={() => retry.mutate()} disabled={retry.isPending}>
          <RotateCcw className="h-4 w-4" aria-hidden /> {t("processing.retry")}
        </button>
      </div>
    );
  }
  const current = STAGES.indexOf(status as (typeof STAGES)[number]);
  return (
    <div className="card p-5" data-testid="processing-status">
      <p className="font-semibold">{status === "ready" ? t("processing.ready") : t("processing.title")}</p>
      <ProgressBar className="mt-3" value={job?.progress_percent ?? 5} label={t("processing.title")} />
      <ol className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
        {STAGES.map((s, i) => (
          <li key={s} className={clsx("flex items-center gap-2", i <= current ? "text-ink" : "text-muted")}>
            {i < current || status === "ready" ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
              : i === current ? <Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden />
              : <span className="h-4 w-4 rounded-full border border-line" aria-hidden />}
            {t(`processing.${s}`)}
          </li>
        ))}
      </ol>
      {status !== "ready" && <p className="mt-4 text-xs text-muted">{t("upload.leaveNote")}</p>}
    </div>
  );
}
