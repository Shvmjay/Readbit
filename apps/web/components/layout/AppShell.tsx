"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, GraduationCap, Home, LogOut, Settings, Upload } from "lucide-react";
import clsx from "clsx";
import { Logo } from "@/components/ui/Logo";
import { Spinner } from "@/components/ui/States";
import { useMe } from "@/hooks/queries";
import { useT } from "@/lib/i18n-client";
import { api } from "@/lib/api";
import { isLocale } from "@/lib/i18n";
import { applyTheme } from "@/lib/theme";
import { LanguageSwitcher } from "./LanguageSwitcher";

const NAV = [
  { href: "/app", key: "nav.home", icon: Home, exact: true },
  { href: "/app/library", key: "nav.library", icon: BookOpen },
  { href: "/app/upload", key: "nav.upload", icon: Upload },
  { href: "/app/learning", key: "nav.learning", icon: GraduationCap },
  { href: "/app/settings", key: "nav.settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useT();
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();
  const { data: me, isLoading } = useMe();

  useEffect(() => {
    if (!isLoading && me && !me.authenticated) router.replace(`/start`);
  }, [isLoading, me, router]);

  // Adopt the account's saved preferences on sign-in.
  useEffect(() => {
    const preferred = me?.user?.preferred_language;
    if (preferred && isLocale(preferred) && preferred !== locale) setLocale(preferred);
    if (me?.user?.theme_preference) applyTheme(me.user.theme_preference);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.user?.preferred_language, me?.user?.theme_preference]);

  async function signOut() {
    await api.post("/auth/logout").catch(() => undefined);
    qc.clear();
    router.push("/");
  }

  if (isLoading || !me?.authenticated) {
    return <div className="flex min-h-screen items-center justify-center"><Spinner label={t("common.loading")} /></div>;
  }
  const active = (href: string, exact?: boolean) => (exact ? pathname === href : pathname.startsWith(href));

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[240px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">{t("nav.skip")}</a>
      <aside className="hidden border-r border-line bg-surface/70 lg:flex lg:flex-col" aria-label={t("nav.main")}>
        <div className="px-5 py-5"><Logo href="/app" /></div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ href, key, icon: Icon, exact }) => (
            <Link key={href} href={href} aria-current={active(href, exact) ? "page" : undefined}
              className={clsx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                active(href, exact) ? "bg-accent-soft text-accent" : "text-muted hover:bg-accent-soft/60 hover:text-ink")}>
              <Icon className="h-4 w-4" aria-hidden /> {t(key)}
            </Link>
          ))}
        </nav>
        <div className="space-y-3 border-t border-line p-4 text-sm">
          <div className="truncate text-muted">
            {me.guest ? <span className="chip">{t("common.guestBadge")}</span> : me.user?.display_name || me.user?.email}
          </div>
          <LanguageSwitcher persist compact />
          <button onClick={signOut} className="btn-ghost w-full justify-start px-2"><LogOut className="h-4 w-4" aria-hidden />{t("common.signOut")}</button>
        </div>
      </aside>

      <div className="flex min-h-screen flex-col pb-20 lg:pb-0">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-line bg-bg/85 px-4 py-3 backdrop-blur lg:hidden">
          <Logo href="/app" />
          <div className="flex items-center gap-2">
            {me.guest && <span className="chip">{t("common.guestBadge")}</span>}
            <LanguageSwitcher persist compact />
          </div>
        </header>
        <main id="main" className="flex-1">{children}</main>
      </div>

      <nav aria-label={t("nav.main")} className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-line bg-surface/95 px-2 py-1.5 backdrop-blur lg:hidden">
        {NAV.map(({ href, key, icon: Icon, exact }) => (
          <Link key={href} href={href} aria-current={active(href, exact) ? "page" : undefined}
            className={clsx("flex min-w-[56px] flex-col items-center gap-0.5 rounded-lg px-2 py-1 text-[0.7rem] font-medium",
              active(href, exact) ? "text-accent" : "text-muted")}>
            <Icon className="h-5 w-5" aria-hidden /> {t(key)}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
