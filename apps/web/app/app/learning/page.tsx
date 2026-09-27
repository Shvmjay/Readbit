"use client";

import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Achievement, Book } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { PageHeader } from "@/components/layout/AppShell";
import { ErrorState, LoadingSkeleton, ProgressBar } from "@/components/ui/States";
import { AchievementCard } from "@/features/quizzer/AchievementCard";

type Progress = { learning: { chapters_total: number; chapters_completed: number; questions_answered: number; correct: number; question_accuracy: number | null } };

export default function LearningPage() {
  const { t } = useT();
  const books = useQuery({ queryKey: ["books", "all"], queryFn: () => api.get<{ items: Book[] }>("/books?limit=50") });
  const ach = useQuery({ queryKey: ["achievements"], queryFn: () => api.get<{ achievements: Achievement[] }>("/users/me/achievements") });
  const ready = (books.data?.items ?? []).filter((b) => b.processing_status === "ready");
  const progress = useQueries({ queries: ready.map((b) => ({ queryKey: ["progress", b.id], queryFn: () => api.get<Progress>(`/books/${b.id}/progress`) })) });
  const totals = progress.reduce((acc, p) => {
    const l = p.data?.learning;
    if (l) { acc.answered += l.questions_answered; acc.correct += l.correct; acc.chapters += l.chapters_completed; }
    return acc;
  }, { answered: 0, correct: 0, chapters: 0 });
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader title={t("learning.title")} subtitle={t("learning.subtitle")} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label={t("learning.questionsAnswered")} value={String(totals.answered)} />
        <Stat label={t("learning.accuracy")} value={totals.answered ? `${Math.round((totals.correct / totals.answered) * 100)}%` : "—"} note={t("learning.accuracyNote")} />
        <Stat label={t("learning.chaptersCompleted")} value={String(totals.chapters)} />
      </div>
      <section aria-labelledby="bip">
        <h2 id="bip" className="text-lg font-semibold">{t("learning.booksInProgress")}</h2>
        {books.isLoading && <LoadingSkeleton className="mt-4" />}
        {books.error && <ErrorState error={books.error} />}
        <ul className="mt-4 grid gap-4 sm:grid-cols-2">
          {ready.map((b, i) => {
            const l = progress[i]?.data?.learning;
            return (
              <li key={b.id} className="card p-4">
                <Link href={`/app/books/${b.id}/learn`} className="font-medium hover:text-accent">{b.title}</Link>
                <p className="mt-1 text-xs text-muted">{l ? `${l.chapters_completed}/${l.chapters_total} · ${l.question_accuracy != null ? t("quiz.accuracy", { p: Math.round(l.question_accuracy * 100) }) : "—"}` : ""}</p>
                <ProgressBar className="mt-3" value={l ? (l.chapters_completed / Math.max(1, l.chapters_total)) * 100 : 0} label={b.title} />
              </li>
            );
          })}
        </ul>
      </section>
      <section aria-labelledby="ach">
        <h2 id="ach" className="text-lg font-semibold">{t("learning.achievements")}</h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ach.data?.achievements.map((a) => <AchievementCard key={a.code} a={a} lockedLabel={t("learning.locked")} />)}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card p-5">
      <p className="eyebrow">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}
