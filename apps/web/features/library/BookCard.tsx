"use client";

import Link from "next/link";
import { FileText, BookMarked } from "lucide-react";
import type { Book } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { ProcessingStatus } from "@/features/upload/ProcessingStatus";

/** A book spine-inspired card. Colour is derived from the title so each book is recognisable. */
export function BookCard({ book, actions }: { book: Book; actions?: React.ReactNode }) {
  const { t } = useT();
  const hue = [...book.title].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <article className="card group flex gap-4 p-4" data-testid="book-card">
      <div aria-hidden className="flex h-24 w-16 shrink-0 flex-col justify-between rounded-lg p-2 text-white shadow-card"
        style={{ background: `linear-gradient(160deg, hsl(${hue} 55% 46%), hsl(${(hue + 30) % 360} 50% 32%))` }}>
        {book.file_format === "pdf" ? <FileText className="h-4 w-4 opacity-80" /> : <BookMarked className="h-4 w-4 opacity-80" />}
        <span className="text-[0.6rem] font-semibold uppercase tracking-wider opacity-90">{book.file_format}</span>
      </div>
      <div className="min-w-0 flex-1">
        <Link href={`/app/books/${book.id}`} className="line-clamp-2 font-semibold leading-snug hover:text-accent">{book.title}</Link>
        <p className="mt-0.5 truncate text-sm text-muted">{book.author ?? t("book.authorUnknown")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
          {book.processing_status === "ready" ? (
            <>
              <span>{t("common.chapters", { n: book.chapter_count })}</span>
              {book.estimated_reading_minutes ? <span>· {t("common.minutes", { n: book.estimated_reading_minutes })}</span> : null}
            </>
          ) : (
            <ProcessingStatus book={book} compact />
          )}
        </div>
        {actions && <div className="mt-3 flex gap-2">{actions}</div>}
      </div>
    </article>
  );
}
