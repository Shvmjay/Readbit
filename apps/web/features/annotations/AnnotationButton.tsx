"use client";

import * as Popover from "@radix-ui/react-popover";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bookmark, NotebookPen } from "lucide-react";
import { api } from "@/lib/api";
import type { Annotation } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/components/ui/States";

type Loc = Annotation["source_location"];

export function useCreateAnnotation(bookId: string) {
  const qc = useQueryClient();
  const toast = useToast();
  const { t } = useT();
  return useMutation({
    mutationFn: (body: { annotation_type: Annotation["annotation_type"]; source_location: Loc; selected_text?: string | null; note_text?: string | null; color?: string | null }) =>
      api.post<{ annotation: Annotation }>(`/books/${bookId}/annotations`, body),
    onSuccess: () => {
      toast({ kind: "success", message: t("annotations.added") });
      qc.invalidateQueries({ queryKey: ["annotations", bookId] });
    },
    onError: (e) => toast({ kind: "error", message: errorMessage(e, t) }),
  });
}

/** Bookmark / note actions for a location (summary section, chapter or passage). */
export function AnnotationButton({ bookId, location, selectedText }: { bookId: string; location: Loc; selectedText?: string }) {
  const { t } = useT();
  const create = useCreateAnnotation(bookId);
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <div className="flex shrink-0 gap-1 opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:focus-within:opacity-100">
      <button type="button" className="btn-ghost p-1.5" aria-label={t("summary.bookmark")} title={t("summary.bookmark")} data-testid="bookmark-btn"
        onClick={() => create.mutate({ annotation_type: "bookmark", source_location: location, selected_text: selectedText ?? null })}>
        <Bookmark className="h-4 w-4" aria-hidden />
      </button>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button type="button" className="btn-ghost p-1.5" aria-label={t("summary.addNote")} title={t("summary.addNote")}><NotebookPen className="h-4 w-4" aria-hidden /></button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content sideOffset={6} collisionPadding={12} className="card z-40 w-72 p-3">
            <label htmlFor="note-input" className="label">{t("annotations.yourNote")}</label>
            <textarea id="note-input" rows={4} maxLength={10000} className="input" placeholder={t("annotations.notePlaceholder")} value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn-primary mt-2 w-full" disabled={!note.trim() || create.isPending}
              onClick={() => create.mutate({ annotation_type: "note", source_location: location, selected_text: selectedText ?? null, note_text: note }, { onSuccess: () => { setNote(""); setOpen(false); } })}>
              {t("annotations.save")}
            </button>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
