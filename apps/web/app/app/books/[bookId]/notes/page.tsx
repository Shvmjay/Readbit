"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Download, Highlighter, NotebookPen, Trash2 } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { Annotation, Chapter } from "@/lib/types";
import { useChapters } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/ui/States";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";

const FILTERS = ["all", "note", "highlight", "bookmark"] as const;
const ICON = { note: NotebookPen, highlight: Highlighter, bookmark: Bookmark };

export default function NotesPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const { t } = useT();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const chapters = useChapters(bookId);
  const q = useQuery({ queryKey: ["annotations", bookId], queryFn: () => api.get<{ items: Annotation[] }>(`/books/${bookId}/annotations`) });
  const del = useMutation({ mutationFn: (id: string) => api.del(`/annotations/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["annotations", bookId] }) });
  const edit = useMutation({ mutationFn: ({ id, note }: { id: string; note: string }) => api.patch(`/annotations/${id}`, { note_text: note }), onSuccess: () => qc.invalidateQueries({ queryKey: ["annotations", bookId] }) });
  const chapterById = new Map<string, Chapter>((chapters.data?.items ?? []).map((c) => [c.id, c]));
  const items = (q.data?.items ?? []).filter((a) => filter === "all" || a.annotation_type === filter);

  async function exportMd() {
    const text = await api.text(`/books/${bookId}/annotations/export`);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    Object.assign(document.createElement("a"), { href: url, download: "readbit-notes.md" }).click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{t("annotations.title")}</h2>
        <button className="btn-secondary" onClick={exportMd}><Download className="h-4 w-4" aria-hidden />{t("annotations.export")}</button>
      </div>
      <div role="tablist" aria-label={t("annotations.title")} className="flex gap-2">
        {FILTERS.map((f) => (
          <button key={f} role="tab" aria-selected={filter === f} onClick={() => setFilter(f)}
            className={clsx("chip", filter === f && "border-accent/40 bg-accent-soft text-accent")}>{t(f === "all" ? "annotations.all" : `annotations.${f}`)}</button>
        ))}
      </div>
      {q.isLoading && <LoadingSkeleton lines={4} />}
      {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && items.length === 0 && <EmptyState icon={<NotebookPen className="h-6 w-6" aria-hidden />} title={t("annotations.empty")} />}
      <ul className="space-y-3" data-testid="annotation-list">
        {items.map((a) => {
          const Icon = ICON[a.annotation_type];
          const ch = a.source_location.chapter_id ? chapterById.get(a.source_location.chapter_id) : undefined;
          const href = a.source_location.kind === "passage"
            ? `/app/books/${bookId}/read?chapter=${a.source_location.chapter_id}&passage=${a.source_location.chunk_id}`
            : `/app/books/${bookId}/summary?chapter=${a.source_location.chapter_id ?? "book"}`;
          return (
            <li key={a.id} className="card p-4" data-testid="annotation">
              <div className="flex items-start justify-between gap-3">
                <p className="flex items-center gap-2 text-xs text-muted"><Icon className="h-3.5 w-3.5" aria-hidden />{t(`annotations.${a.annotation_type}`)}{ch && <> · <Link href={href} className="hover:text-accent">{ch.title}</Link></>}</p>
                <ConfirmationDialog trigger={<button className="btn-ghost p-1" aria-label={t("common.delete")}><Trash2 className="h-4 w-4" aria-hidden /></button>}
                  title={t("common.delete")} body={t("annotations.deleteConfirm")} confirmLabel={t("common.delete")} onConfirm={() => del.mutate(a.id)} />
              </div>
              {a.selected_text && (
                <blockquote className="reading mt-2 border-l-2 border-line pl-3 text-base text-ink/80"><span className="sr-only">{t("annotations.fromBook")}: </span>{a.selected_text}</blockquote>
              )}
              {a.note_text != null && <EditableNote value={a.note_text} onSave={(note) => edit.mutate({ id: a.id, note })} />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EditableNote({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(value);
  if (!editing) {
    return (
      <div className="mt-3 rounded-lg bg-accent-soft/50 p-3 text-sm">
        <p className="text-xs font-medium text-accent">{t("annotations.yourNote")}</p>
        <p className="mt-1 whitespace-pre-wrap">{value}</p>
        <button className="mt-2 text-xs text-accent" onClick={() => setEditing(true)}>{t("common.edit")}</button>
      </div>
    );
  }
  return (
    <div className="mt-3 space-y-2">
      <textarea className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label={t("annotations.yourNote")} />
      <div className="flex gap-2">
        <button className="btn-primary px-3 py-1.5" disabled={!text.trim()} onClick={() => { onSave(text); setEditing(false); }}>{t("common.save")}</button>
        <button className="btn-ghost px-3 py-1.5" onClick={() => { setText(value); setEditing(false); }}>{t("common.cancel")}</button>
      </div>
    </div>
  );
}
