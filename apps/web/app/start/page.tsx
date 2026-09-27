"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookHeart, ShieldCheck } from "lucide-react";
import { api, track } from "@/lib/api";
import { useT } from "@/lib/i18n-client";
import { useMe, useMeta } from "@/hooks/queries";
import { AuthCard } from "@/features/auth/AuthCard";
import { LanguageSwitcher } from "@/components/layout/LanguageSwitcher";
import { errorMessage } from "@/components/ui/States";

export default function Start() {
  const { t, locale } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: meta } = useMeta();
  const [ack, setAck] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hours = meta?.limits.guest_retention_hours ?? 24;

  async function continueAsGuest() {
    if (!ack) {
      setError(t("onboarding.ackRequired"));
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/guest", { language: locale, accepted_privacy: true });
      track("onboarding_completed", { source: "guest" });
      await qc.invalidateQueries({ queryKey: ["me"] });
      router.push("/app");
    } catch (e) {
      setError(errorMessage(e, t));
      setBusy(false);
    }
  }

  return (
    <AuthCard title={t("onboarding.title")} subtitle={t("onboarding.subtitle")}>
      {me?.authenticated && (
        <Link href="/app" className="btn-primary mb-6 w-full">{t("common.continue")}</Link>
      )}
      <div className="space-y-5">
        <LanguageSwitcher />
        <div className="flex gap-3 rounded-xl bg-accent-soft/60 p-4 text-sm">
          <BookHeart className="h-5 w-5 shrink-0 text-accent" aria-hidden />
          <p>{t("onboarding.sourceNote")}</p>
        </div>
        <section aria-labelledby="privacy-title" className="rounded-xl border border-line p-4 text-sm">
          <h2 id="privacy-title" className="flex items-center gap-2 font-medium"><ShieldCheck className="h-4 w-4 text-accent" aria-hidden />{t("onboarding.privacyTitle")}</h2>
          <p className="mt-2 text-muted">{t("onboarding.privacyGuest", { hours })}</p>
          <p className="mt-1 text-muted">{t("onboarding.privacyUser")} <Link href="/privacy" className="text-accent underline">{t("landing.footerPrivacy")}</Link></p>
          <label className="mt-3 flex items-start gap-2">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[rgb(var(--accent))]" checked={ack} onChange={(e) => { setAck(e.target.checked); setError(null); }} data-testid="privacy-ack" />
            <span>{t("onboarding.ack")}</span>
          </label>
        </section>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <button className="btn-primary w-full" onClick={continueAsGuest} disabled={busy} data-testid="continue-guest">{t("onboarding.guest")}</button>
        <div className="grid grid-cols-2 gap-3">
          <Link href="/register" className="btn-secondary">{t("onboarding.register")}</Link>
          <Link href="/login" className="btn-secondary">{t("onboarding.login")}</Link>
        </div>
      </div>
    </AuthCard>
  );
}
