import { describe, expect, it } from "vitest";
import en from "@/locales/en.json";
import hi from "@/locales/hi.json";
import { getDictionary, translate } from "@/lib/i18n";

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  return Object.entries(obj).reduce<Record<string, string>>((acc, [k, v]) => {
    if (v && typeof v === "object") Object.assign(acc, flatten(v as Record<string, unknown>, `${prefix}${k}.`));
    else acc[`${prefix}${k}`] = String(v);
    return acc;
  }, {});
}

describe("localization", () => {
  const E = flatten(en);
  const H = flatten(hi);

  it("Hindi has exactly the English keys", () => {
    expect(Object.keys(H).sort()).toEqual(Object.keys(E).sort());
  });

  it("placeholders match in every translation", () => {
    for (const key of Object.keys(E)) {
      const ph = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort();
      expect(ph(H[key]!), key).toEqual(ph(E[key]!));
    }
  });

  it("no Hindi string is left untranslated where English has letters (except brand/format names)", () => {
    const allowed = new Set(["brand.name"]);
    const untranslated = Object.keys(E).filter((k) => !allowed.has(k) && E[k] === H[k] && /[a-z]{4,}/i.test(E[k]!));
    expect(untranslated).toEqual([]);
  });

  it("interpolates variables and falls back to English", () => {
    expect(translate(getDictionary("en"), "quiz.question", { i: 2, n: 5 })).toBe("Question 2 of 5");
    expect(translate(getDictionary("hi"), "quiz.question", { i: 2, n: 5 })).toBe("प्रश्न 2 / 5");
    expect(translate(getDictionary("hi"), "missing.key")).toBe("missing.key");
  });
});
