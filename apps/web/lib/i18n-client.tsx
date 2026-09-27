"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { getDictionary, LOCALE_COOKIE, translate } from "./i18n";
import type { Language } from "./types";

type Ctx = { locale: Language; t: (key: string, vars?: Record<string, string | number>) => string; setLocale: (l: Language) => void };
const I18nContext = createContext<Ctx | null>(null);

export function I18nProvider({ initialLocale, children }: { initialLocale: Language; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Language>(initialLocale);
  const dict = useMemo(() => getDictionary(locale), [locale]);
  const t = useCallback((key: string, vars?: Record<string, string | number>) => translate(dict, key, vars), [dict]);
  const setLocale = useCallback((l: Language) => {
    setLocaleState(l);
    document.cookie = `${LOCALE_COOKIE}=${l}; path=/; max-age=31536000; samesite=lax`;
    document.documentElement.lang = l;
  }, []);
  const value = useMemo(() => ({ locale, t, setLocale }), [locale, t, setLocale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

// Used when a component renders outside the provider (e.g. a boundary rendered without the root layout during
// prerendering): fall back to the default language rather than crashing the page.
const fallbackDict = getDictionary("en");
const FALLBACK: Ctx = { locale: "en", t: (key, vars) => translate(fallbackDict, key, vars), setLocale: () => undefined };

export function useT() {
  return useContext(I18nContext) ?? FALLBACK;
}
