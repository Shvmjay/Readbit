"use client";

import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Play, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { Lesson, MasteryItem, QuizQuestion, QuizSession } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { ErrorState, LoadingSkeleton, errorMessage } from "@/components/ui/States";
import { MasteryIndicator } from "@/features/quizzer/MasteryIndicator";
import { useToast } from "@/components/ui/Toast";

export default function LessonsPage() {
  const { bookId } = useParams<{ bookId: string }>();
  const { t } = useT();
  const router = useRouter();
  const toast = useToast();
  const lessons = useQuery({
    queryKey: ["lessons", bookId],
    queryFn: () => api.get<{ items: Lesson[] }>(`/books/${bookId}/lessons`),
    refetchInterval: (q) => (q.state.data?.items.some((l) => l.bank_status === "generating") ? 2000 : false),
  });
  const mastery = useQuery({ queryKey: ["mastery", bookId], queryFn: () => api.get<{ items: MasteryItem[] }>(`/books/${bookId}/mastery`) });
  type View = { session: QuizSession; question: QuizQuestion | null };
  const start = useMutation({
    mutationFn: (chapterId: string | null) => api.post<View>(`/books/${bookId}/quiz-sessions`, { chapter_id: chapterId }),
    onSuccess: (v) => router.push(`/app/books/${bookId}/learn/${v.session.id}`),
    onError: (e) => toast({ kind: "error", message: errorMessage(e, t) }),
  });
  const revise = useMutation({
    mutationFn: () => api.post<View>(`/books/${bookId}/revision-sessions`),
    onSuccess: (v) => router.push(`/app/books/${bookId}/learn/${v.session.id}`),
    onError: (e) => toast({ kind: "error", message: errorMessage(e, t) }),
  });
  const weakCount = mastery.data?.items.filter((m) => m.weak).length ?? 0;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-semibold">{t("quiz.lessons")}</h2>
          <button className="btn-primary" onClick={() => start.mutate(null)} disabled={start.isPending} data-testid="continue-lesson">
            {start.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}{t("quiz.continue")}
          </button>
        </div>
        {lessons.isLoading && <LoadingSkeleton lines={5} />}
        {lessons.error && <ErrorState error={lessons.error} onRetry={() => lessons.refetch()} />}
        <ol className="space-y-3" data-testid="lesson-list">
          {lessons.data?.items.map((l) => (
            <li key={l.chapter_id} className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
              <div aria-hidden className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-semibold ${l.completed ? "bg-success text-white" : "bg-accent-soft text-accent"}`}>
                {l.completed ? <CheckCircle2 className="h-5 w-5" /> : l.ordinal}
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-medium">{l.title}</p>
                <p className="text-xs text-muted">
                  {l.bank_status === "generating" ? t("quiz.generating") : l.approved_questions ? t("quiz.questionsReady", { n: l.approved_questions }) : t("quiz.noBank")}
                  {l.accuracy != null && ` · ${t("quiz.accuracy", { p: Math.round(l.accuracy * 100) })}`}
                  {l.completed && ` · ${t("quiz.completed")}`}
                </p>
              </div>
              <button className="btn-secondary shrink-0" onClick={() => start.mutate(l.chapter_id)} disabled={start.isPending} data-testid={`start-lesson-${l.ordinal}`}>
                {l.lessons_completed ? t("quiz.review") : t("quiz.start")}
              </button>
            </li>
          ))}
        </ol>
      </div>
      <aside className="space-y-4">
        <section className="card p-5">
          <h2 className="font-semibold">{t("quiz.revision")}</h2>
          <p className="mt-1 text-sm text-muted">{t("quiz.revisionBody")}</p>
          <button className="btn-secondary mt-4 w-full" onClick={() => revise.mutate()} disabled={revise.isPending || weakCount === 0} data-testid="start-revision">
            <RefreshCw className="h-4 w-4" aria-hidden />{weakCount === 0 ? t("quiz.nothingToRevise") : t("quiz.revision")}
          </button>
        </section>
        <MasteryIndicator items={mastery.data?.items ?? []} />
      </aside>
    </div>
  );
}
