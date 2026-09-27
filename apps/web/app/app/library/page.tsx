"use client";

import Link from "next/link";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, Upload, Library as LibraryIcon } from "lucide-react";
import { api } from "@/lib/api";
import type { Book } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { PageHeader } from "@/components/layout/AppShell";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/ui/States";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";
import { useToast } from "@/components/ui/Toast";
import { BookCard } from "@/features/library/BookCard";

export default function LibraryPage() {
  const { t } = useT();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useInfiniteQuery({
    queryKey: ["books"],
    queryFn: ({ pageParam }) => api.get<{ items: Book[]; next_cursor: string | null }>(`/books?limit=12${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: (query) => (query.state.data?.pages.some((p) => p.items.some((b) => !["ready", "failed"].includes(b.processing_status))) ? 2000 : false),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.del(`/books/${id}`),
    onSuccess: () => {
      toast({ kind: "success", message: t("library.deleted") });
      qc.invalidateQueries({ queryKey: ["books"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const books = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title={t("library.title")} subtitle={t("library.subtitle")}
        actions={<Link href="/app/upload" className="btn-primary"><Upload className="h-4 w-4" aria-hidden />{t("dashboard.upload")}</Link>} />
      {q.isLoading && <LoadingSkeleton lines={5} />}
      {q.error && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && books.length === 0 && (
        <EmptyState icon={<LibraryIcon className="h-6 w-6" aria-hidden />} title={t("dashboard.emptyTitle")} body={t("dashboard.emptyBody")}
          action={<Link href="/app/upload" className="btn-primary">{t("dashboard.upload")}</Link>} />
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {books.map((b) => (
          <BookCard key={b.id} book={b} actions={
            <ConfirmationDialog
              trigger={<button className="btn-ghost px-2 py-1 text-xs" aria-label={`${t("library.delete")}: ${b.title}`}><Trash2 className="h-3.5 w-3.5" aria-hidden />{t("common.delete")}</button>}
              title={t("library.delete")} body={t("library.deleteConfirm", { title: b.title })} confirmLabel={t("common.delete")}
              onConfirm={() => del.mutate(b.id)} />
          } />
        ))}
      </div>
      {q.hasNextPage && (
        <div className="text-center"><button className="btn-secondary" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>{t("library.loadMore")}</button></div>
      )}
    </div>
  );
}
