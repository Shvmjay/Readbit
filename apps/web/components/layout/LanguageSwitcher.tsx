"use client";

import { Languages } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useT } from "@/lib/i18n-client";
import { LOCALES, LOCALE_NAMES } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { Language } from "@/lib/types";

export function LanguageSwitcher({ persist = false, compact = false }: { persist?: boolean; compact?: boolean }) {
  const { locale, setLocale, t } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  async function change(l: Language) {
    setLocale(l);
    router.refresh(); // re-render server components (landing, legal pages) in the new language
    if (persist) {
      await api.patch("/me/preferences", { preferred_language: l }).catch(() => undefined);
      qc.invalidateQueries({ queryKey: ["me"] });
    }
  }
  return (
    <label className="inline-flex items-center gap-1.5 text-sm text-muted">
      <Languages className="h-4 w-4" aria-hidden />
      <span className={compact ? "sr-only" : ""}>{t("settings.language")}</span>
      <select value={locale} onChange={(e) => void change(e.target.value as Language)}
        className="rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink" data-testid="language-select">
        {LOCALES.map((l) => (
          <option key={l} value={l}>{LOCALE_NAMES[l]}</option>
        ))}
      </select>
    </label>
  );
}
