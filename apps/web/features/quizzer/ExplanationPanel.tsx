"use client";

import { CheckCircle2, Lightbulb, XCircle } from "lucide-react";
import type { AnswerFeedback } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { track } from "@/lib/api";
import { locationLabel } from "@/features/summarizer/SourceCitation";
import Link from "next/link";
import { useEffect } from "react";

export function ExplanationPanel({ bookId, feedback }: { bookId: string; feedback: AnswerFeedback }) {
  const { t } = useT();
  useEffect(() => track("explanation_opened", {}, bookId), [bookId, feedback.question_id]);
  return (
    <section role="status" aria-live="polite" data-testid="answer-feedback"
      className={feedback.is_correct ? "rounded-2xl border border-success/40 bg-success/10 p-5" : "rounded-2xl border border-danger/40 bg-danger/10 p-5"}>
      <p className="flex items-center gap-2 text-lg font-semibold">
        {feedback.is_correct ? <CheckCircle2 className="h-5 w-5 text-success" aria-hidden /> : <XCircle className="h-5 w-5 text-danger" aria-hidden />}
        {feedback.is_correct ? t("quiz.correct") : t("quiz.incorrect")}
      </p>
      <p className="mt-2 text-sm"><span className="font-medium">{t("quiz.correctAnswer")}:</span> <span data-testid="correct-answer">{feedback.correct_option_key}. {feedback.correct_option_text}</span></p>
      <div className="mt-3 text-sm">
        <p className="font-medium">{t("quiz.why")}</p>
        <p className="mt-1 leading-relaxed">{feedback.explanation}</p>
      </div>
      {feedback.misconception && (
        <p className="mt-3 flex gap-2 text-sm"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden /><span><span className="font-medium">{t("quiz.misconception")}:</span> {feedback.misconception}</span></p>
      )}
      {feedback.evidence.map((ev) => (
        <div key={ev.id} className="mt-4 rounded-xl bg-surface/80 p-3 text-sm" data-testid="feedback-evidence">
          <p className="eyebrow">{t("quiz.support")} · {locationLabel(ev, t)}</p>
          <blockquote className="reading mt-1 text-[0.95rem]">{ev.excerpt}</blockquote>
          <Link className="mt-2 inline-block text-xs font-medium text-accent" href={`/app/books/${bookId}/read?chapter=${ev.chapter_id ?? ""}&passage=${ev.chunk_id}`}>{t("evidence.openInSource")}</Link>
        </div>
      ))}
    </section>
  );
}
