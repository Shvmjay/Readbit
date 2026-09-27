"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, LogOut } from "lucide-react";
import { api } from "@/lib/api";
import type { Language } from "@/lib/types";
import { useT } from "@/lib/i18n-client";
import { useMe, useMeta } from "@/hooks/queries";
import { PageHeader } from "@/components/layout/AppShell";
import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";
import { useToast } from "@/components/ui/Toast";
import { errorMessage } from "@/components/ui/States";
import { applyTheme, type Theme } from "@/lib/theme";
import { LOCALE_NAMES } from "@/lib/i18n";

export default function SettingsPage() {
  const { t } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: me } = useMe();
  const { data: meta } = useMeta();
  const user = me?.user;
  const [confirm, setConfirm] = useState("");
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch("/me/preferences", body),
    onSuccess: () => { toast({ kind: "success", message: t("settings.saved") }); qc.invalidateQueries({ queryKey: ["me"] }); },
    onError: (e) => toast({ kind: "error", message: errorMessage(e, t) }),
  });
  function setTheme(theme: Theme) {
    applyTheme(theme);
    if (user) save.mutate({ theme_preference: theme });
  }
  async function exportData() {
    const data = await api.get("/me/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: "readbit-export.json" }).click();
    URL.revokeObjectURL(url);
  }
  async function deleteAccount() {
    try {
      await api.del("/me", { confirm: "DELETE" });
      qc.clear();
      router.push("/");
    } catch (e) {
      toast({ kind: "error", message: errorMessage(e, t) });
    }
  }
  async function signOut() {
    await api.post("/auth/logout").catch(() => undefined);
    qc.clear();
    router.push("/");
  }
  const currentTheme = (typeof window !== "undefined" && (localStorage.getItem("rb_theme") as Theme)) || user?.theme_preference || "system";
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader title={t("settings.title")} />
      {me?.guest && (
        <section className="card p-5">
          <h2 className="font-semibold">{t("settings.guestTitle")}</h2>
          <p className="mt-1 text-sm text-muted">{t("settings.guestBody", { hours: meta?.limits.guest_retention_hours ?? 24 })}</p>
          <Link href="/register" className="btn-primary mt-4">{t("onboarding.register")}</Link>
        </section>
      )}
      <section className="card space-y-5 p-5" aria-labelledby="prefs">
        <h2 id="prefs" className="font-semibold">{t("settings.preferences")}</h2>
        <LanguageSwitcher persist />
        {user && (
          <label className="flex items-center gap-2 text-sm text-muted">
            {t("settings.contentLanguage")}
            <select className="rounded-lg border border-line bg-surface px-2 py-1 text-ink" defaultValue={user.content_language} onChange={(e) => save.mutate({ content_language: e.target.value as Language })}>
              {(["en", "hi"] as Language[]).map((l) => <option key={l} value={l}>{LOCALE_NAMES[l]}</option>)}
            </select>
          </label>
        )}
        <fieldset>
          <legend className="text-sm text-muted">{t("settings.theme")}</legend>
          <div className="mt-2 flex gap-2">
            {(["light", "dark", "system"] as Theme[]).map((th) => (
              <label key={th} className="chip cursor-pointer has-[:checked]:border-accent/50 has-[:checked]:bg-accent-soft has-[:checked]:text-accent">
                <input type="radio" name="theme" className="sr-only" defaultChecked={currentTheme === th} onChange={() => setTheme(th)} />{t(`settings.${th}`)}
              </label>
            ))}
          </div>
        </fieldset>
        {user && (
          <label className="flex items-center gap-2 text-sm text-muted">
            {t("settings.goal")}
            <input type="number" min={1} max={200} defaultValue={user.daily_goal_questions} className="input w-24 py-1.5"
              onBlur={(e) => { const v = Number(e.target.value); if (v >= 1 && v <= 200 && v !== user.daily_goal_questions) save.mutate({ daily_goal_questions: v }); }} />
          </label>
        )}
      </section>
      <section className="card space-y-4 p-5" aria-labelledby="data">
        <h2 id="data" className="font-semibold">{t("settings.data")}</h2>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={exportData}><Download className="h-4 w-4" aria-hidden />{t("settings.export")}</button>
          <button className="btn-secondary" onClick={signOut}><LogOut className="h-4 w-4" aria-hidden />{t("common.signOut")}</button>
        </div>
        {user && (
          <div className="border-t border-line pt-4">
            <p className="text-sm text-muted">{t("settings.deleteBody")}</p>
            <ConfirmationDialog trigger={<button className="btn-danger mt-3">{t("settings.deleteAccount")}</button>}
              title={t("settings.deleteAccount")} body={t("settings.deleteBody")} confirmLabel={t("settings.deleteAccount")}
              confirmDisabled={confirm !== "DELETE"} onConfirm={deleteAccount}>
              <label className="label mt-4" htmlFor="confirm-delete">{t("settings.deleteConfirmLabel")}</label>
              <input id="confirm-delete" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
            </ConfirmationDialog>
          </div>
        )}
      </section>
    </div>
  );
}
