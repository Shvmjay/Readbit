"use client";

import clsx from "clsx";
import type { Depth } from "@/lib/types";
import { useT } from "@/lib/i18n-client";

const DEPTHS: Depth[] = ["concise", "balanced", "comprehensive"];

export function SummaryDepthSelector({ value, onChange }: { value: Depth; onChange: (d: Depth) => void }) {
  const { t } = useT();
  return (
    <div role="radiogroup" aria-label={t("summary.depth")} className="inline-flex rounded-xl border border-line bg-surface p-1">
      {DEPTHS.map((d) => (
        <button key={d} type="button" role="radio" aria-checked={value === d} onClick={() => onChange(d)} data-testid={`depth-${d}`}
          className={clsx("rounded-lg px-3 py-1.5 text-sm font-medium transition-colors", value === d ? "bg-accent text-accent-ink" : "text-muted hover:text-ink")}>
          {t(`summary.${d}`)}
        </button>
      ))}
    </div>
  );
}
