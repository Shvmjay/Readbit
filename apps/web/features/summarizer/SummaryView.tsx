"use client";

import { useMemo } from "react";
import { AlertTriangle, Bot, FileSearch, Lightbulb, ListChecks, MessageSquareQuote, ShieldAlert, Sparkles } from "lucide-react";
import type { Summary } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { Citations } from "./SourceCitation";
import { AnnotationButton } from "@/features/annotations/AnnotationButton";

export function SummaryView({ bookId, summary }: { bookId: string; summary: Summary }) {
  const { t } = useT();
  const c = summary.content!;
  // Citation numbers are assigned in reading order and shared across the whole summary.
  const numbering = useMemo(() => new Map<string, number>(), [summary.id]); // eslint-disable-line react-hooks/exhaustive-deps
  numbering.clear();
  const cite = (ids: string[]) => <Citations bookId={bookId} ids={ids} evidence={summary.evidence} numbering={numbering} />;
  const cov = c.coverage;
  return (
    <article className="space-y-8" data-testid="summary-view" lang={summary.output_language}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="chip"><Bot className="h-3.5 w-3.5" aria-hidden />{c.engine.mode === "extractive" ? t("summary.engineExtractive") : t("summary.engineGenerative")}</span>
        <span className="chip"><FileSearch className="h-3.5 w-3.5" aria-hidden />
          {summary.scope === "book" && cov.chapters_total != null
            ? t("summary.chaptersCovered", { covered: cov.chapters_covered ?? 0, total: cov.chapters_total })
            : t("summary.coverage", { cited: cov.source_passages_cited ?? 0, total: cov.source_passages_considered ?? 0 })}
        </span>
        <span className="chip">{t("summary.readTime", { a: c.reading_minutes, b: c.source_reading_minutes })}</span>
      </div>

      {(cov.known_gaps?.length ?? 0) > 0 && (
        <aside className="rounded-2xl border border-warning/40 bg-warning/10 p-4 text-sm" aria-label={t("summary.gaps")}>
          <p className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4 text-warning" aria-hidden />{t("summary.gaps")}</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">{cov.known_gaps!.map((g) => <li key={g}>{g}</li>)}</ul>
        </aside>
      )}

      {c.central_thesis.text && (
        <section aria-labelledby="thesis" className="rounded-2xl border border-accent/25 bg-accent-soft/50 p-5">
          <h2 id="thesis" className="eyebrow flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" aria-hidden />{t("summary.thesis")}</h2>
          <p className="reading mt-2 text-[1.15rem]">{c.central_thesis.text}{cite(c.central_thesis.evidence_ids)}</p>
        </section>
      )}

      <div className="space-y-7">
        {c.sections.map((s, i) => (
          <section key={i} id={`section-${i}`} data-section-key={`sections.${i}`} className="group scroll-mt-24">
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-xl font-semibold">{s.heading}</h2>
              <AnnotationButton bookId={bookId} location={{ kind: "summary", summary_id: summary.id, section_key: `sections.${i}` }} selectedText={s.heading} />
            </div>
            <p className="reading mt-2">{s.content}{cite(s.evidence_ids)}</p>
            {s.key_concepts.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5" aria-label={t("summary.keyConcepts")}>
                {s.key_concepts.map((k) => <span key={k} className="chip">{k}</span>)}
              </div>
            )}
          </section>
        ))}
      </div>

      {c.definitions.length > 0 && (
        <Block title={t("summary.definitions")} icon={<Lightbulb className="h-4 w-4" aria-hidden />}>
          <dl className="space-y-3">
            {c.definitions.map((d, i) => (
              <div key={i}><dt className="font-semibold">{d.term}</dt><dd className="reading text-base text-ink/90">{d.definition}{cite(d.evidence_ids)}</dd></div>
            ))}
          </dl>
        </Block>
      )}
      {c.examples.length > 0 && (
        <Block title={t("summary.examples")} icon={<MessageSquareQuote className="h-4 w-4" aria-hidden />}>
          <ul className="space-y-2">{c.examples.map((e, i) => <li key={i} className="reading text-base">{e.description}{cite(e.evidence_ids)}</li>)}</ul>
        </Block>
      )}
      {c.caveats.length > 0 && (
        <Block title={t("summary.caveats")} icon={<ShieldAlert className="h-4 w-4" aria-hidden />}>
          <ul className="space-y-2">{c.caveats.map((e, i) => <li key={i} className="reading text-base">{e.text}{cite(e.evidence_ids)}</li>)}</ul>
        </Block>
      )}
      {c.connections.length > 0 && (
        <Block title={t("summary.connections")}>
          <ul className="space-y-2">{c.connections.map((e, i) => <li key={i} className="reading text-base">{e.text}{cite(e.evidence_ids)}</li>)}</ul>
        </Block>
      )}
      {c.conclusion.text && (
        <Block title={t("summary.conclusion")}><p className="reading text-base">{c.conclusion.text}{cite(c.conclusion.evidence_ids)}</p></Block>
      )}
      {c.takeaways.length > 0 && (
        <Block title={t("summary.takeaways")} icon={<ListChecks className="h-4 w-4" aria-hidden />}>
          <ol className="list-decimal space-y-2 pl-5">{c.takeaways.map((e, i) => <li key={i} className="reading text-base">{e.text}{cite(e.evidence_ids)}</li>)}</ol>
        </Block>
      )}
    </article>
  );
}

function Block({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="eyebrow mb-3 flex items-center gap-1.5">{icon}{title}</h2>
      {children}
    </section>
  );
}
