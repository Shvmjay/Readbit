"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, BrainCircuit, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import { useBook, useChapters } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { LoadingSkeleton, ProgressBar } from "@/components/ui/States";
import { ProcessingStatus } from "@/features/upload/ProcessingStatus";
import { LOCALE_NAMES, isLocale } from "@/lib/i18n";

export default function Overview() {
  const { bookId } = useParams<{ bookId: string }>();
  const { t } = useT();
  const { data } = useBook(bookId);
  const book = data?.book;
  const ready = book?.processing_status === "ready";
  const chapters = useChapters(bookId, ready);
  const progress = useQuery({
    queryKey: ["progress", bookId],
    queryFn: () => api.get<{ reading: { chapters_total: number; chapters_read: number }; learning: { chapters_completed: number } }>(`/books/${bookId}/progress`),
    enabled: ready,
  });
  if (!book) return null;
  if (!ready) return <div className="max-w-2xl"><ProcessingStatus book={book} /></div>;
  const lang = book.detected_language;
  const facts: [string, string][] = [
    [t("book.author"), book.author ?? t("common.unknown")],
    [t("book.format"), book.file_format.toUpperCase() + (book.page_count ? ` · ${t("common.pages", { n: book.page_count })}` : "")],
    [t("book.language"), lang ? (isLocale(lang) ? LOCALE_NAMES[lang] : lang) : t("common.unknown")],
    [t("book.chapters"), String(book.chapter_count)],
    [t("book.readingTime"), book.estimated_reading_minutes ? t("common.minutes", { n: book.estimated_reading_minutes }) : t("common.unknown")],
  ];
  const r = progress.data;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <div className="space-y-6">
        {book.warnings.length > 0 && (
          <section className="rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm" aria-labelledby="warn-title">
            <h2 id="warn-title" className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4 text-warning" aria-hidden />{t("book.warnings")}</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">{book.warnings.map((w) => <li key={w.code + w.message}>{w.message}</li>)}</ul>
          </section>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Link href={`/app/books/${bookId}/summary`} className="card group p-5 hover:border-accent/50" data-testid="go-summarize">
            <ScrollText className="h-6 w-6 text-accent" aria-hidden />
            <p className="mt-3 font-semibold">{t("book.summarize")}</p>
            <p className="mt-1 text-sm text-muted">{t("landing.how2Body")}</p>
          </Link>
          <Link href={`/app/books/${bookId}/learn`} className="card group p-5 hover:border-accent/50" data-testid="go-learn">
            <BrainCircuit className="h-6 w-6 text-accent" aria-hidden />
            <p className="mt-3 font-semibold">{t("book.learn")}</p>
            <p className="mt-1 text-sm text-muted">{t("landing.how3Body")}</p>
          </Link>
        </div>
        <section className="card p-5" aria-labelledby="toc-title">
          <h2 id="toc-title" className="text-lg font-semibold">{t("book.toc")}</h2>
          {(book.structure_confidence ?? 1) < 0.5 && <p className="mt-2 text-sm text-warning">{t("book.structureWarning")}</p>}
          {chapters.isLoading && <LoadingSkeleton className="mt-4" />}
          <ol className="mt-3 divide-y divide-line" data-testid="toc">
            {chapters.data?.items.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-3">
                <Link href={`/app/books/${bookId}/summary?chapter=${c.id}`} className="min-w-0 hover:text-accent">
                  <span className="mr-2 text-sm text-muted">{c.ordinal}.</span><span className="font-medium">{c.title}</span>
                </Link>
                <span className="shrink-0 text-xs text-muted">{c.estimated_reading_minutes ? t("common.minutes", { n: c.estimated_reading_minutes }) : ""}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
      <aside className="space-y-4">
        <dl className="card divide-y divide-line p-5 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3 py-2"><dt className="text-muted">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
          ))}
        </dl>
        {r && (
          <div className="card space-y-4 p-5 text-sm">
            <div>
              <p className="flex justify-between"><span>{t("book.summaryProgress")}</span><span className="text-muted">{r.reading.chapters_read}/{r.reading.chapters_total}</span></p>
              <ProgressBar className="mt-2" value={(r.reading.chapters_read / Math.max(1, r.reading.chapters_total)) * 100} label={t("book.summaryProgress")} />
            </div>
            <div>
              <p className="flex justify-between"><span>{t("book.quizProgress")}</span><span className="text-muted">{r.learning.chapters_completed}/{r.reading.chapters_total}</span></p>
              <ProgressBar className="mt-2" value={(r.learning.chapters_completed / Math.max(1, r.reading.chapters_total)) * 100} label={t("book.quizProgress")} />
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
