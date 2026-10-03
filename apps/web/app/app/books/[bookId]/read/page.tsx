"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Highlighter, NotebookPen } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { Annotation, Chapter, Passage } from "@/lib/types";
import { useChapters } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { ErrorState, LoadingSkeleton } from "@/components/ui/States";
import { useCreateAnnotation } from "@/features/annotations/AnnotationButton";
import { useToast } from "@/components/ui/Toast";

type Selection = { chunkId: string; text: string; start: number; end: number };

function ReaderInner() {
  const { bookId } = useParams<{ bookId: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { t } = useT();
  const toast = useToast();
  const chapters = useChapters(bookId);
  const chapterId = params.get("chapter") || chapters.data?.items[0]?.id;
  const target = params.get("passage");
  const q = useQuery({
    queryKey: ["passages", bookId, chapterId],
    enabled: !!chapterId,
    queryFn: () => api.get<{ chapter: Chapter; items: Passage[] }>(`/books/${bookId}/chapters/${chapterId}/passages`),
  });
  const anns = useQuery({ queryKey: ["annotations", bookId], queryFn: () => api.get<{ items: Annotation[] }>(`/books/${bookId}/annotations`) });
  const create = useCreateAnnotation(bookId);
  const [sel, setSel] = useState<Selection | null>(null);
  const [note, setNote] = useState("");
  const targetRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (q.data && targetRef.current) targetRef.current.scrollIntoView({ block: "center" });
  }, [q.data, target]);
  useEffect(() => {
    if (chapterId) api.put(`/books/${bookId}/reading-state`, { view: "source", chapter_id: chapterId }).catch(() => undefined);
  }, [bookId, chapterId]);

  function captureSelection() {
    const s = window.getSelection();
    if (!s || s.isCollapsed) return setSel(null);
    const node = s.anchorNode?.parentElement?.closest("[data-chunk-id]") as HTMLElement | null;
    const text = s.toString().trim();
    if (!node || !text) return setSel(null);
    const full = node.dataset.text ?? "";
    const start = Math.max(0, full.indexOf(text.slice(0, 40)));
    setSel({ chunkId: node.dataset.chunkId!, text: text.slice(0, 2000), start, end: start + text.length });
  }
  function annotate(kind: "highlight" | "note") {
    if (!sel) return toast({ kind: "error", message: t("reader.noSelection") });
    create.mutate({
      annotation_type: kind, source_location: { kind: "passage", chunk_id: sel.chunkId, start: sel.start, end: sel.end },
      selected_text: sel.text, note_text: kind === "note" ? note : null, color: kind === "highlight" ? "yellow" : null,
    }, { onSuccess: () => { setSel(null); setNote(""); window.getSelection()?.removeAllRanges(); } });
  }
  const highlights = (anns.data?.items ?? []).filter((a) => a.annotation_type === "highlight" && a.selected_text);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <div className="min-w-0 space-y-4">
        <div className="card flex flex-col gap-2 p-4 sm:flex-row sm:items-center">
          <label htmlFor="reader-chapter" className="shrink-0 text-sm text-muted">{t("summary.chapter")}</label>
          <select id="reader-chapter" className="input py-2" value={chapterId ?? ""} onChange={(e) => router.push(`/app/books/${bookId}/read?chapter=${e.target.value}`)}>
            {chapters.data?.items.map((c) => <option key={c.id} value={c.id}>{c.ordinal}. {c.title}</option>)}
          </select>
        </div>
        <p className="text-sm text-muted">{t("reader.hint")}</p>
        {q.isLoading && <LoadingSkeleton lines={10} />}
        {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
        {q.data && (
          <article className="card bg-paper p-5 sm:p-8" onMouseUp={captureSelection} onTouchEnd={captureSelection} aria-label={t("reader.title")}>
            <h2 className="mb-6 text-2xl font-semibold">{q.data.chapter.title}</h2>
            {q.data.items.map((p, i) => {
              const showSection = p.section_title && p.section_title !== q.data!.items[i - 1]?.section_title && p.section_title !== q.data!.chapter.title;
              return (
                <div key={p.id} id={p.id} ref={p.id === target ? targetRef : undefined} data-chunk-id={p.id} data-text={p.text}
                  className={clsx("scroll-mt-24 rounded-lg transition-colors", p.id === target && "bg-accent-soft/60 p-3 ring-1 ring-accent/30")}>
                  {showSection && <h3 className="mb-3 mt-6 text-lg font-semibold">{p.section_title}</h3>}
                  <p className="mb-1 text-[0.7rem] text-muted">{t("reader.passage", { p: p.passage.slice(1) })}{p.page_number ? ` · ${t("evidence.page", { p: p.page_label ?? p.page_number })}` : ""}</p>
                  {p.text.split("\n\n").map((para, j) => (
                    <p key={j} className="reading mb-4">{renderHighlights(para, highlights.filter((h) => h.source_location.chunk_id === p.id).map((h) => h.selected_text!))}</p>
                  ))}
                </div>
              );
            })}
          </article>
        )}
      </div>
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <div className="card space-y-3 p-4">
          <p className="text-sm font-medium">{sel ? `“${sel.text.slice(0, 120)}${sel.text.length > 120 ? "…" : ""}”` : t("reader.hint")}</p>
          <button className="btn-secondary w-full" disabled={!sel} onClick={() => annotate("highlight")} data-testid="highlight-btn"><Highlighter className="h-4 w-4" aria-hidden />{t("annotations.highlight")}</button>
          <label htmlFor="reader-note" className="sr-only">{t("annotations.yourNote")}</label>
          <textarea id="reader-note" rows={3} className="input" placeholder={t("annotations.notePlaceholder")} value={note} onChange={(e) => setNote(e.target.value)} disabled={!sel} />
          <button className="btn-primary w-full" disabled={!sel || !note.trim()} onClick={() => annotate("note")}><NotebookPen className="h-4 w-4" aria-hidden />{t("annotations.save")}</button>
        </div>
      </aside>
    </div>
  );
}

function renderHighlights(text: string, marks: string[]) {
  const mark = marks.find((m) => m.length > 3 && text.includes(m));
  if (!mark) return text;
  const i = text.indexOf(mark);
  return (<>{text.slice(0, i)}<mark className="rounded bg-yellow-200/70 px-0.5 text-ink dark:bg-yellow-400/30">{mark}</mark>{text.slice(i + mark.length)}</>);
}

export default function ReaderPage() {
  return <Suspense><ReaderInner /></Suspense>;
}
