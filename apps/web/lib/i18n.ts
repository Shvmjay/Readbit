import en from "@/locales/en.json";
import hi from "@/locales/hi.json";
import type { Language } from "./types";

export const LOCALES: Language[] = ["en", "hi"];
export const DEFAULT_LOCALE: Language = "en";
export const LOCALE_COOKIE = "rb_locale";
export const LOCALE_NAMES: Record<Language, string> = { en: "English", hi: "हिन्दी" };

export type Dictionary = typeof en;
const DICTS: Record<Language, Dictionary> = { en, hi };

export function isLocale(value: unknown): value is Language {
  return typeof value === "string" && (LOCALES as string[]).includes(value);
}

export function getDictionary(locale: Language): Dictionary {
  return DICTS[locale] ?? en;
}

/** Look up "a.b.c" and interpolate {placeholders}. Falls back to English, then to the key itself. */
export function translate(dict: Dictionary, key: string, vars?: Record<string, string | number>): string {
  const lookup = (d: unknown): string | undefined => {
    let cur: unknown = d;
    for (const part of key.split(".")) {
      if (cur && typeof cur === "object" && part in (cur as Record<string, unknown>)) cur = (cur as Record<string, unknown>)[part];
      else return undefined;
    }
    return typeof cur === "string" ? cur : undefined;
  };
  const raw = lookup(dict) ?? lookup(en) ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m));
}
