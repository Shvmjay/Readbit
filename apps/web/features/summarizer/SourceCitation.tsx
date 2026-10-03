"use client";

import Link from "next/link";
import * as Popover from "@radix-ui/react-popover";
import { useState } from "react";
import { BookOpen, Languages } from "lucide-react";
import type { Evidence, Language } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { api, track } from "@/lib/api";
import { useMeta } from "@/hooks/queries";
import { errorMessage, Spinner } from "@/components/ui/States";

export function locationLabel(ev: Evidence, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (ev.page_number) {
    const printed = ev.page_label && ev.page_label !== String(ev.page_number) ? ` (${t("evidence.printed", { p: ev.page_label })})` : "";
    return t("evidence.page", { p: ev.page_number }) + printed;
  }
  return [ev.section_title, ev.passage].filter(Boolean).join(" · ");
}

/** Citation chip → popover with the supporting excerpt, its location, and a link into the source reader. */
export function SourceCitation({ bookId, evidence, index }: { bookId: string; evidence: Evidence | undefined; index: number }) {
  const { t, locale } = useT();
  const { data: meta } = useMeta();
  const [translation, setTranslation] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!evidence) return null;
  async function translate() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ translation: string }>(`/books/${bookId}/evidence/${evidence!.id}/translate`, { target_language: locale as Language });
      setTranslation(r.translation);
    } catch (e) {
      setErr(errorMessage(e, t));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Popover.Root onOpenChange={(open) => open && track("source_citation_opened", {}, bookId)}>
      <Popover.Trigger asChild>
        <button type="button" className="mx-0.5 inline-flex -translate-y-1 items-center rounded-md bg-accent-soft px-1.5 py-0.5 align-baseline text-[0.7rem] font-semibold text-accent hover:bg-accent hover:text-accent-ink"
          aria-label={`${t("summary.citation", { n: index })}: ${locationLabel(evidence, t)}`} data-testid="citation">
          {index}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} collisionPadding={12} className="card z-40 w-[min(26rem,calc(100vw-2rem))] p-4 text-sm" data-testid="evidence-popover">
          <p className="eyebrow">{t("evidence.title")} · {locationLabel(evidence, t)}</p>
          <blockquote className="reading mt-2 border-l-2 border-accent/50 pl-3 text-[0.95rem]">{evidence.excerpt}</blockquote>
          {evidence.extraction_confidence < 0.9 && <p className="mt-2 text-xs text-warning">{t("evidence.ocr")}</p>}
          {translation && (
            <div className="mt-3 rounded-lg bg-accent-soft/60 p-3">
              <p className="text-xs font-medium text-muted">{t("evidence.translation")}</p>
              <p className="mt-1">{translation}</p>
            </div>
          )}
          {err && <p className="mt-2 text-xs text-danger">{err}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <Link className="btn-secondary px-3 py-1.5 text-xs" href={`/app/books/${bookId}/read?chapter=${evidence.chapter_id ?? ""}&passage=${evidence.chunk_id}`}>
              <BookOpen className="h-3.5 w-3.5" aria-hidden />{t("evidence.openInSource")}
            </Link>
            {meta?.ai_engine.can_translate && !translation && (
              <button className="btn-ghost px-3 py-1.5 text-xs" onClick={translate} disabled={busy}>
                {busy ? <Spinner /> : <Languages className="h-3.5 w-3.5" aria-hidden />}{t("evidence.translate")}
              </button>
            )}
          </div>
          <Popover.Arrow className="fill-[rgb(var(--surface))]" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function Citations({ bookId, ids, evidence, numbering }: { bookId: string; ids: string[]; evidence: Record<string, Evidence>; numbering: Map<string, number> }) {
  return (
    <>
      {ids.map((id) => {
        if (!numbering.has(id)) numbering.set(id, numbering.size + 1);
        return <SourceCitation key={id} bookId={bookId} evidence={evidence[id]} index={numbering.get(id)!} />;
      })}
    </>
  );
}
