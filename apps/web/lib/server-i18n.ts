import { cookies } from "next/headers";
import { DEFAULT_LOCALE, getDictionary, isLocale, LOCALE_COOKIE } from "./i18n";

export async function serverDictionary() {
  const store = await cookies();
  const value = store.get(LOCALE_COOKIE)?.value;
  const locale = isLocale(value) ? value : DEFAULT_LOCALE;
  return { locale, d: getDictionary(locale) };
}
