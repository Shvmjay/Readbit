"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, PartyPopper, Trophy } from "lucide-react";
import { api } from "@/lib/api";
import type { AnswerFeedback, QuizQuestion, QuizSession } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { EmptyState, ErrorState, LoadingSkeleton, ProgressBar } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { QuizQuestionCard } from "@/features/quizzer/QuizQuestionCard";
import { ExplanationPanel } from "@/features/quizzer/ExplanationPanel";

type View = { session: QuizSession; question: QuizQuestion | null };

export default function QuizPlayer() {
  const { bookId, sessionId } = useParams<{ bookId: string; sessionId: string }>();
  const { t } = useT();
  const toast = useToast();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<AnswerFeedback | null>(null);
  const shownAt = useRef<number>(Date.now());
  const view = useQuery({
    queryKey: ["quiz-session", sessionId],
    queryFn: () => api.get<View>(`/quiz-sessions/${sessionId}`),
    refetchInterval: (q) => (q.state.data?.session.status === "preparing" ? 2000 : false),
  });
  const question = view.data?.question;
  useEffect(() => {
    shownAt.current = Date.now();
  }, [question?.id]);

  const submit = useMutation({
    mutationFn: () => api.post<AnswerFeedback>(`/quiz-sessions/${sessionId}/answers`, {
      question_id: question!.id, selected_option_key: selected, response_duration_ms: Date.now() - shownAt.current,
    }),
    onSuccess: (fb) => {
      setFeedback(fb);
      fb.achievements_earned.forEach((a) => toast({ kind: "achievement", message: `${t("quiz.achievement")}: ${a.name}` }));
      qc.invalidateQueries({ queryKey: ["lessons", bookId] });
      qc.invalidateQueries({ queryKey: ["mastery", bookId] });
    },
  });
  async function next() {
    setFeedback(null);
    setSelected(null);
    await view.refetch();
    window.scrollTo({ top: 0 });
  }

  if (view.isLoading) return <LoadingSkeleton lines={6} />;
  if (view.error) return <ErrorState error={view.error} onRetry={() => view.refetch()} />;
  const s = feedback?.session ?? view.data!.session;
  const progress = (s.answered_count / Math.max(1, s.question_count)) * 100;

  if (s.status === "preparing") {
    return (
      <div className="card mx-auto max-w-2xl p-8 text-center" role="status" aria-live="polite" data-testid="quiz-preparing">
        <Loader2 className="mx-auto h-8 w-8 animate-spin text-accent" aria-hidden />
        <p className="mt-4 font-semibold">{t("quiz.preparing")}</p>
        <p className="mt-2 text-sm text-muted">{t("quiz.preparingBody")}</p>
      </div>
    );
  }
  if (s.status === "unavailable") {
    return <div className="mx-auto max-w-2xl"><EmptyState title={t("quiz.unavailable")} body={s.status_message} action={<Link href={`/app/books/${bookId}/learn`} className="btn-secondary">{t("quiz.backToLessons")}</Link>} /></div>;
  }
  if (s.status === "completed" && !feedback) {
    const perfect = s.answered_count > 0 && s.correct_count === s.answered_count;
    return (
      <div className="card mx-auto max-w-2xl p-8 text-center" data-testid="quiz-result">
        {perfect ? <Trophy className="mx-auto h-10 w-10 text-accent" aria-hidden /> : <PartyPopper className="mx-auto h-10 w-10 text-accent" aria-hidden />}
        <h2 className="mt-4 text-2xl font-semibold">{t("quiz.resultTitle")}</h2>
        <p className="mt-2 text-muted">{t("quiz.resultScore", { c: s.correct_count, n: s.answered_count })}</p>
        <ProgressBar className="mx-auto mt-6 max-w-sm" value={(s.correct_count / Math.max(1, s.answered_count)) * 100} label={t("learning.accuracy")} />
        <Link href={`/app/books/${bookId}/learn`} className="btn-primary mt-8">{t("quiz.backToLessons")}</Link>
      </div>
    );
  }
  if (!question && !feedback) return <LoadingSkeleton lines={4} />;
  const q = question!;
  const isLast = s.answered_count >= s.question_count;
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <div className="flex justify-between text-sm text-muted">
          <span data-testid="question-counter">{t("quiz.question", { i: Math.min(s.answered_count + (feedback ? 0 : 1), s.question_count), n: s.question_count })}</span>
          <span>{s.session_type === "revision" ? t("quiz.revision") : ""}</span>
        </div>
        <ProgressBar className="mt-2" value={progress} label={t("quiz.lessons")} />
      </div>
      <div className="card p-5 sm:p-7">
        <QuizQuestionCard question={q} selected={selected} onSelect={setSelected} feedback={feedback} />
        {!feedback && (
          <button className="btn-primary mt-6 w-full py-3" disabled={!selected || submit.isPending} onClick={() => submit.mutate()} data-testid="submit-answer">
            {submit.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}{t("quiz.submit")}
          </button>
        )}
        {submit.error && <div className="mt-4"><ErrorState error={submit.error} onRetry={() => submit.mutate()} /></div>}
      </div>
      {feedback && (
        <>
          <ExplanationPanel bookId={bookId} feedback={feedback} />
          <button className="btn-primary w-full py-3" onClick={next} data-testid="next-question" autoFocus>
            {isLast ? t("quiz.finish") : t("quiz.next")}<ArrowRight className="h-4 w-4" aria-hidden />
          </button>
        </>
      )}
    </div>
  );
}
