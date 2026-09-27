"use client";

import type { MasteryItem } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import clsx from "clsx";

export function MasteryIndicator({ items }: { items: MasteryItem[] }) {
  const { t } = useT();
  if (!items.length) return null;
  return (
    <section className="card p-5" aria-labelledby="mastery-title">
      <h2 id="mastery-title" className="font-semibold">{t("quiz.mastery")}</h2>
      <p className="mt-1 text-xs text-muted">{t("quiz.masteryNote")}</p>
      <ul className="mt-4 space-y-3">
        {items.map((m) => (
          <li key={m.topic_id} className="text-sm">
            <div className="flex justify-between gap-3"><span className={clsx("truncate", m.weak && "font-medium text-warning")}>{m.topic}</span><span className="shrink-0 text-muted">{Math.round(m.mastery_score * 100)}%</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line/70" role="meter" aria-valuenow={Math.round(m.mastery_score * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={m.topic}>
              <div className={clsx("h-full rounded-full", m.weak ? "bg-warning" : "bg-success")} style={{ width: `${m.mastery_score * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
