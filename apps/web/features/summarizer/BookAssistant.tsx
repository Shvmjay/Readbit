"use client";

import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageCircleQuestion, SearchX } from "lucide-react";
import { api } from "@/lib/api";
import type { QaAnswer } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { ErrorState, Spinner } from "@/components/ui/States";
import { SourceCitation } from "./SourceCitation";

type Turn = { question: string; answer: QaAnswer };

export function BookAssistant({ bookId, chapterId }: { bookId: string; chapterId: string | null }) {
  const { t } = useT();
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<"book" | "chapter">("book");
  const [turns, setTurns] = useState<Turn[]>([]);
  const ask = useMutation({
    mutationFn: (q: string) => api.post<QaAnswer>(`/books/${bookId}/questions`, { question: q, chapter_id: scope === "chapter" ? chapterId : null }),
    onSuccess: (answer, q) => {
      setTurns((prev) => [{ question: q, answer }, ...prev]);
      setQuestion("");
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (question.trim()) ask.mutate(question.trim());
  }
  return (
    <section className="card flex flex-col p-4" aria-labelledby="assistant-title" data-testid="book-assistant">
      <h2 id="assistant-title" className="flex items-center gap-2 font-semibold"><MessageCircleQuestion className="h-4 w-4 text-accent" aria-hidden />{t("assistant.title")}</h2>
      <p className="mt-1 text-xs text-muted">{t("assistant.onlyBook")}</p>
      <form onSubmit={submit} className="mt-3 space-y-2">
        <label htmlFor="qa-input" className="sr-only">{t("assistant.placeholder")}</label>
        <textarea id="qa-input" rows={2} maxLength={1000} className="input resize-none" placeholder={t("assistant.placeholder")} value={question}
          onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }} />
        <div className="flex items-center justify-between gap-2">
          {chapterId ? (
            <select className="rounded-lg border border-line bg-surface px-2 py-1 text-xs" value={scope} onChange={(e) => setScope(e.target.value as "book" | "chapter")} aria-label={t("summary.scope")}>
              <option value="book">{t("assistant.scopeBook")}</option>
              <option value="chapter">{t("assistant.scopeChapter")}</option>
            </select>
          ) : <span />}
          <button className="btn-primary px-3 py-1.5" disabled={ask.isPending || !question.trim()}>{t("assistant.ask")}</button>
        </div>
      </form>
      <div className="mt-4 space-y-4" aria-live="polite">
        {ask.isPending && <Spinner label={t("assistant.thinking")} />}
        {ask.error && <ErrorState error={ask.error} />}
        {turns.map((turn, i) => (
          <div key={i} className="border-t border-line pt-3 text-sm" data-testid="qa-turn">
            <p className="font-medium">{turn.question}</p>
            {turn.answer.answerable ? (
              <>
                <p className="reading mt-2 text-[0.95rem]">
                  {turn.answer.answer}
                  {turn.answer.citations.map((c, j) => <SourceCitation key={c.id} bookId={bookId} evidence={c} index={j + 1} />)}
                </p>
                <p className="mt-1 text-xs text-muted">{t("assistant.confidence", { c: turn.answer.confidence })}</p>
              </>
            ) : (
              <div className="mt-2 flex gap-2 rounded-lg bg-line/40 p-3" data-testid="qa-abstain">
                <SearchX className="h-4 w-4 shrink-0 text-muted" aria-hidden />
                <div><p className="font-medium">{t("assistant.notInBook")}</p><p className="text-muted">{turn.answer.unanswerable_reason}</p></div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
