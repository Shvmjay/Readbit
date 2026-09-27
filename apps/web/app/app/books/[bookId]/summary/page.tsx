"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Loader2 } from "lucide-react";
import { api, ApiError, track } from "@/lib/api";
import type { Depth, Language, Summary } from "@/lib/types";
import { useBook, useChapters, useMeta } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { ErrorState, LoadingSkeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { SummaryDepthSelector } from "@/features/summarizer/SummaryDepthSelector";
import { SummaryView } from "@/features/summarizer/SummaryView";
import { BookAssistant } from "@/features/summarizer/BookAssistant";
import { AnnotationButton } from "@/features/annotations/AnnotationButton";
import { LOCALE_NAMES } from "@/lib/i18n";

function SummarizerInner() {
  const { bookId } = useParams<{ bookId: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { t } = useT();
  const toast = useToast();
  const qc = useQueryClient();
  const { data: bookData } = useBook(bookId);
  const { data: meta } = useMeta();
  const chapters = useChapters(bookId);
  const reading = bookData?.reading_state;
  const chapterParam = params.get("chapter");
  const chapterId = chapterParam === "book" ? null : chapterParam ?? reading?.last_chapter_id ?? chapters.data?.items[0]?.id ?? null;
  const [depth, setDepth] = useState<Depth>((params.get("depth") as Depth) || reading?.last_depth || "balanced");
  const [language, setLanguage] = useState<Language | "">("");
  const scrollRatio = useRef<number | null>(null);

  const request = useQuery({
    queryKey: ["summary-request", bookId, chapterId, depth, language],
    enabled: chapters.isSuccess,
    queryFn: () => api.post<{ summary: Summary }>(`/books/${bookId}/summaries`, { chapter_id: chapterId, depth, output_language: language || null }),
    staleTime: Infinity,
  });
  const summaryId = request.data?.summary.id;
  const poll = useQuery({
    queryKey: ["summary", summaryId],
    enabled: !!summaryId,
    queryFn: () => api.get<{ summary: Summary }>(`/books/${bookId}/summaries/${summaryId}`),
    refetchInterval: (q) => (["pending", "generating"].includes(q.state.data?.summary.status ?? "pending") ? 1500 : false),
  });
  const summary = poll.data?.summary;

  // Persist reading position and restore scroll after a depth switch.
  const save = useMutation({ mutationFn: (body: Record<string, unknown>) => api.put<{ achievements_earned: { name: string }[] }>(`/books/${bookId}/reading-state`, body) });
  useEffect(() => {
    if (summary?.status !== "ready") return;
    save.mutate({ view: "summary", chapter_id: chapterId, depth }, {
      onSuccess: (r) => {
        r.achievements_earned.forEach((a) => toast({ kind: "achievement", message: `${t("quiz.achievement")}: ${a.name}` }));
        qc.invalidateQueries({ queryKey: ["progress", bookId] });
      },
    });
    track(chapterId ? "chapter_summary_opened" : "summary_depth_changed", { depth }, bookId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary?.id, summary?.status]);
  useLayoutEffect(() => {
    if (summary?.status === "ready" && scrollRatio.current != null) {
      window.scrollTo({ top: scrollRatio.current * document.body.scrollHeight });
      scrollRatio.current = null;
    }
  }, [summary?.status, summary?.id]);

  function changeDepth(d: Depth) {
    scrollRatio.current = window.scrollY / Math.max(1, document.body.scrollHeight);
    setDepth(d);
    track("summary_depth_changed", { depth: d }, bookId);
  }
  function goChapter(id: string | null) {
    router.push(`/app/books/${bookId}/summary?chapter=${id ?? "book"}`);
    window.scrollTo({ top: 0 });
  }
  async function exportMd() {
    if (!summary) return;
    const text = await api.text(`/books/${bookId}/summaries/${summary.id}/export`);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `readbit-summary.md` });
    a.click();
    URL.revokeObjectURL(url);
  }

  const items = chapters.data?.items ?? [];
  const idx = items.findIndex((c) => c.id === chapterId);
  const error = request.error || poll.error;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-5">
        <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:flex-wrap sm:items-center">
          <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
            <span className="shrink-0 text-muted">{t("summary.scope")}</span>
            <select className="input py-2" value={chapterId ?? "book"} onChange={(e) => goChapter(e.target.value === "book" ? null : e.target.value)} data-testid="scope-select">
              <option value="book">{t("summary.wholeBook")}</option>
              {items.map((c) => <option key={c.id} value={c.id}>{c.ordinal}. {c.title}</option>)}
            </select>
          </label>
          <SummaryDepthSelector value={depth} onChange={changeDepth} />
          {meta?.ai_engine.can_translate && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted">{t("summary.outputLanguage")}</span>
              <select className="rounded-lg border border-line bg-surface px-2 py-1.5" value={language} onChange={(e) => setLanguage(e.target.value as Language | "")}>
                <option value="">—</option>
                {(["en", "hi"] as Language[]).map((l) => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}
              </select>
            </label>
          )}
        </div>

        {error && <ErrorState error={error} onRetry={() => { request.refetch(); }} />}
        {!error && (!summary || summary.status === "pending" || summary.status === "generating") && (
          <div className="card p-6" role="status" aria-live="polite">
            <p className="flex items-center gap-2 font-medium"><Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden />{t("summary.generating")}</p>
            <p className="mt-1 text-sm text-muted">{t("summary.generatingBody")}</p>
            <LoadingSkeleton className="mt-5" lines={6} />
          </div>
        )}
        {summary?.status === "failed" && (
          <ErrorState error={new ApiError(502, { code: summary.error?.code ?? "internal_error", message: summary.error?.message ?? "", retryable: true }, t("summary.failed"))} onRetry={() => { qc.removeQueries({ queryKey: ["summary-request", bookId] }); request.refetch(); }} />
        )}
        {summary?.status === "ready" && summary.content && (
          <div className="card bg-paper p-5 sm:p-8">
            <div className="mb-6 flex items-start justify-between gap-3 border-b border-line pb-4">
              <div>
                <p className="eyebrow">{chapterId ? t("summary.chapter") : t("summary.wholeBook")} · {t(`summary.${summary.depth}`)}</p>
                <h2 className="mt-1 text-2xl font-semibold">{summary.content.title}</h2>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {chapterId && <AnnotationButton bookId={bookId} location={{ kind: "chapter", chapter_id: chapterId }} selectedText={summary.content.title} />}
                <button className="btn-ghost px-2" onClick={exportMd} aria-label={t("summary.export")} title={t("summary.export")}><Download className="h-4 w-4" aria-hidden /></button>
              </div>
            </div>
            <SummaryView bookId={bookId} summary={summary} />
            {chapterId && (
              <nav className="mt-10 flex justify-between gap-3 border-t border-line pt-4" aria-label={t("book.chapters")}>
                <button className="btn-ghost" disabled={idx <= 0} onClick={() => goChapter(items[idx - 1]!.id)}><ChevronLeft className="h-4 w-4" aria-hidden />{t("summary.prevChapter")}</button>
                <button className="btn-ghost" disabled={idx < 0 || idx >= items.length - 1} onClick={() => goChapter(items[idx + 1]!.id)} data-testid="next-chapter">{t("summary.nextChapter")}<ChevronRight className="h-4 w-4" aria-hidden /></button>
              </nav>
            )}
          </div>
        )}
      </div>
      <div className="lg:sticky lg:top-6 lg:self-start">
        <BookAssistant bookId={bookId} chapterId={chapterId} />
      </div>
    </div>
  );
}

export default function SummarizerPage() {
  return <Suspense><SummarizerInner /></Suspense>;
}
