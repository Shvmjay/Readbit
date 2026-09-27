"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";
import clsx from "clsx";
import { BookOpen, BrainCircuit, LayoutGrid, NotebookPen, ScrollText } from "lucide-react";
import { useBook } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { ErrorState, LoadingSkeleton } from "@/components/ui/States";

export default function BookLayout({ children }: { children: ReactNode }) {
  const { bookId } = useParams<{ bookId: string }>();
  const pathname = usePathname();
  const { t } = useT();
  const { data, error, isLoading, refetch } = useBook(bookId);
  const base = `/app/books/${bookId}`;
  const tabs = [
    { href: base, label: t("book.overview"), icon: LayoutGrid, exact: true },
    { href: `${base}/summary`, label: t("book.summarizer"), icon: ScrollText },
    { href: `${base}/learn`, label: t("book.quizzer"), icon: BrainCircuit },
    { href: `${base}/read`, label: t("book.read"), icon: BookOpen },
    { href: `${base}/notes`, label: t("book.notes"), icon: NotebookPen },
  ];
  if (isLoading) return <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6"><LoadingSkeleton lines={6} /></div>;
  if (error || !data) return <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6"><ErrorState error={error} onRetry={() => refetch()} /></div>;
  const book = data.book;
  const ready = book.processing_status === "ready";
  return (
    <div>
      <div className="border-b border-line bg-surface/60">
        <div className="mx-auto max-w-6xl px-4 pt-6 sm:px-6">
          <p className="eyebrow">{book.file_format.toUpperCase()} · {ready ? t("common.chapters", { n: book.chapter_count }) : t(`processing.${book.processing_status}`)}</p>
          <h1 className="mt-1 text-2xl font-semibold sm:text-3xl" data-testid="book-title">{book.title}</h1>
          <p className="mt-1 text-sm text-muted">{book.author ?? t("book.authorUnknown")}</p>
          <nav aria-label={book.title} className="-mb-px mt-5 flex gap-1 overflow-x-auto">
            {tabs.map(({ href, label, icon: Icon, exact }) => {
              const active = exact ? pathname === href : pathname.startsWith(href);
              const disabled = !ready && href !== base;
              return disabled ? (
                <span key={href} className="flex shrink-0 items-center gap-1.5 border-b-2 border-transparent px-3 py-2.5 text-sm text-muted/50" aria-disabled="true">
                  <Icon className="h-4 w-4" aria-hidden />{label}
                </span>
              ) : (
                <Link key={href} href={href} aria-current={active ? "page" : undefined}
                  className={clsx("flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium",
                    active ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink")}>
                  <Icon className="h-4 w-4" aria-hidden />{label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">{children}</div>
    </div>
  );
}
