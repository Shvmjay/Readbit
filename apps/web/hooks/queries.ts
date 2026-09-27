"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Book, Chapter, Me, Meta, ReadingState } from "@/lib/types";

export const qk = {
  me: ["me"] as const,
  meta: ["meta"] as const,
  dashboard: ["dashboard"] as const,
  books: ["books"] as const,
  book: (id: string) => ["book", id] as const,
  chapters: (id: string) => ["chapters", id] as const,
  lessons: (id: string) => ["lessons", id] as const,
  annotations: (id: string) => ["annotations", id] as const,
  progress: (id: string) => ["progress", id] as const,
  mastery: (id: string) => ["mastery", id] as const,
  achievements: ["achievements"] as const,
};

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api.get<Me>("/me"), staleTime: 60_000 });
}

export function useMeta() {
  return useQuery({ queryKey: qk.meta, queryFn: () => api.get<Meta>("/meta"), staleTime: 10 * 60_000 });
}

export function useBook(bookId: string) {
  return useQuery({
    queryKey: qk.book(bookId),
    queryFn: () => api.get<{ book: Book; reading_state: ReadingState | null }>(`/books/${bookId}`),
    // Poll while the book is processing so status stays accurate without blocking the UI.
    refetchInterval: (q) => {
      const s = q.state.data?.book.processing_status;
      return s && s !== "ready" && s !== "failed" ? 1500 : false;
    },
  });
}

export function useChapters(bookId: string, enabled = true) {
  return useQuery({ queryKey: qk.chapters(bookId), queryFn: () => api.get<{ items: Chapter[]; structure_confidence: number | null }>(`/books/${bookId}/chapters`), enabled });
}
