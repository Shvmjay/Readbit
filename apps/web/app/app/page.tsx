"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { BookOpenCheck, BrainCircuit, Flame, Target, Upload, AlertCircle, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { useMe } from "@/hooks/queries";
import { PageHeader } from "@/components/layout/AppShell";
import { EmptyState, ErrorState, LoadingSkeleton, ProgressBar } from "@/components/ui/States";
import { BookCard } from "@/features/library/BookCard";
import { relativeTime } from "@/lib/format";

export default function DashboardPage() {
  const { t, locale } = useT();
  const { data: me } = useMe();
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/me/dashboard"),
    refetchInterval: (query) => (query.state.data?.recent_books.some((b) => !["ready", "failed"].includes(b.processing_status)) ? 2000 : false),
  });
  const name = me?.user?.display_name ? `, ${me.user.display_name}` : "";
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader title={t("dashboard.greeting", { name })}
        actions={<Link href="/app/upload" className="btn-primary"><Upload className="h-4 w-4" aria-hidden />{t("dashboard.upload")}</Link>} />
      {me?.guest && q.data?.guest_expires_at && (
        <div className="flex flex-col gap-3 rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm sm:flex-row sm:items-center sm:justify-between" role="note">
          <p className="flex items-center gap-2"><AlertCircle className="h-4 w-4 shrink-0 text-warning" aria-hidden />{t("dashboard.guestNotice", { when: relativeTime(q.data.guest_expires_at, locale) })}</p>
          <Link href="/register" className="btn-secondary shrink-0">{t("dashboard.keep")}</Link>
        </div>
      )}
      {q.isLoading && <LoadingSkeleton lines={6} />}
      {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && q.data.recent_books.length === 0 && (
        <EmptyState icon={<Upload className="h-6 w-6" aria-hidden />} title={t("dashboard.emptyTitle")}
          body={<><p>{t("dashboard.emptyBody")}</p><ul className="mt-4 space-y-2 text-left">
            <li className="flex gap-2"><BookOpenCheck className="h-4 w-4 shrink-0 text-accent" aria-hidden />{t("dashboard.emptyPoint1")}</li>
            <li className="flex gap-2"><BrainCircuit className="h-4 w-4 shrink-0 text-accent" aria-hidden />{t("dashboard.emptyPoint2")}</li></ul></>}
          action={<Link href="/app/upload" className="btn-primary">{t("dashboard.upload")}</Link>} />
      )}
      {q.data && q.data.recent_books.length > 0 && <DashboardBody d={q.data} />}
    </div>
  );
}

function DashboardBody({ d }: { d: Dashboard }) {
  const { t } = useT();
  const goalPct = Math.round((d.daily_goal.answered_today / Math.max(1, d.daily_goal.target)) * 100);
  return (
    <>
      <div className="grid gap-4 md:grid-cols-3">
        <section className="card p-5 md:col-span-2" aria-labelledby="cont-title">
          <h2 id="cont-title" className="eyebrow">{t("dashboard.continueReading")}</h2>
          {d.continue_reading.length === 0 ? (
            <p className="mt-3 text-sm text-muted">—</p>
          ) : (
            <ul className="mt-3 divide-y divide-line">
              {d.continue_reading.slice(0, 3).map((c) => (
                <li key={c.book.id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{c.book.title}</p>
                    <p className="truncate text-sm text-muted">{c.chapter?.title ?? t("summary.wholeBook")}</p>
                    <ProgressBar className="mt-2 w-48 max-w-full" value={(c.state.chapters_read.length / Math.max(1, c.chapters_total)) * 100} label={t("book.summaryProgress")} />
                  </div>
                  <Link className="btn-secondary shrink-0" href={`/app/books/${c.book.id}/summary${c.chapter ? `?chapter=${c.chapter.id}` : ""}`}>{t("dashboard.resume")}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card space-y-4 p-5" aria-label={t("dashboard.goal")}>
          <div>
            <p className="eyebrow flex items-center gap-1.5"><Target className="h-3.5 w-3.5" aria-hidden />{t("dashboard.goal")}</p>
            <p className="mt-2 text-sm">{t("dashboard.goalProgress", { a: d.daily_goal.answered_today, b: d.daily_goal.target })}</p>
            <ProgressBar className="mt-2" value={goalPct} label={t("dashboard.goal")} />
          </div>
          <div>
            <p className="eyebrow flex items-center gap-1.5"><Flame className="h-3.5 w-3.5" aria-hidden />{t("dashboard.streak")}</p>
            <p className="mt-1 text-2xl font-semibold">{t("dashboard.streakDays", { n: d.streak_days })}</p>
          </div>
        </section>
      </div>

      {d.continue_learning && (
        <section className="card flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="eyebrow">{t("dashboard.continueLearning")}</p>
            <p className="mt-1 font-medium">{d.continue_learning.book_title}</p>
            <p className="text-sm text-muted">{t("quiz.question", { i: d.continue_learning.answered_count + 1, n: d.continue_learning.question_count })}</p>
          </div>
          <Link className="btn-primary" href={`/app/books/${d.continue_learning.book_id}/learn/${d.continue_learning.id}`}>{t("quiz.continue")}<ArrowRight className="h-4 w-4" aria-hidden /></Link>
        </section>
      )}

      <section aria-labelledby="recent-title">
        <div className="flex items-center justify-between">
          <h2 id="recent-title" className="text-lg font-semibold">{t("dashboard.recentBooks")}</h2>
          <Link href="/app/library" className="text-sm font-medium text-accent">{t("dashboard.viewLibrary")}</Link>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {d.recent_books.slice(0, 6).map((b) => <BookCard key={b.id} book={b} />)}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card p-5" aria-labelledby="weak-title">
          <h2 id="weak-title" className="eyebrow">{t("dashboard.weak")}</h2>
          {d.weak_concepts.length === 0 ? <p className="mt-3 text-sm text-muted">{t("dashboard.noWeak")}</p> : (
            <ul className="mt-3 space-y-2">
              {d.weak_concepts.map((w) => (
                <li key={w.book_id + w.topic} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0"><span className="font-medium">{w.topic}</span> <span className="text-muted">· {w.book_title}</span></span>
                  <Link href={`/app/books/${w.book_id}/learn`} className="shrink-0 text-accent">{t("quiz.revision")}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card p-5" aria-labelledby="lessons-title">
          <h2 id="lessons-title" className="eyebrow">{t("dashboard.recentLessons")}</h2>
          {d.recently_completed_lessons.length === 0 ? <p className="mt-3 text-sm text-muted">—</p> : (
            <ul className="mt-3 space-y-2 text-sm">
              {d.recently_completed_lessons.map((l) => (
                <li key={l.completed_at} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">{l.chapter_title} <span className="text-muted">· {l.book_title}</span></span>
                  <span className="shrink-0 text-muted">{t("dashboard.lessonScore", { c: l.correct, n: l.answered })}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
