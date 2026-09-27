import Link from "next/link";
import { Logo } from "@/components/ui/Logo";
import { LanguageSwitcher } from "./LanguageSwitcher";
import type { Dictionary } from "@/lib/i18n";

export function PublicHeader({ d }: { d: Dictionary }) {
  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Logo />
        <nav aria-label={d.nav.main} className="flex items-center gap-2 sm:gap-4">
          <LanguageSwitcher compact />
          <Link href="/login" className="btn-ghost hidden sm:inline-flex">{d.onboarding.login}</Link>
          <Link href="/start" className="btn-primary whitespace-nowrap px-3 sm:px-4">{d.landing.ctaStart}</Link>
        </nav>
      </div>
    </header>
  );
}

export function PublicFooter({ d }: { d: Dictionary }) {
  return (
    <footer className="border-t border-line bg-surface/60">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div>
          <Logo />
          <p className="mt-2 max-w-md">{d.landing.footerNote}</p>
        </div>
        <nav aria-label="Legal" className="flex flex-wrap gap-4">
          <Link href="/privacy" className="hover:text-ink">{d.landing.footerPrivacy}</Link>
          <Link href="/terms" className="hover:text-ink">{d.landing.footerTerms}</Link>
          <Link href="/copyright" className="hover:text-ink">{d.landing.footerCopyright}</Link>
          <a href="mailto:hello@readbit.example" className="hover:text-ink">{d.landing.footerContact}</a>
        </nav>
      </div>
    </footer>
  );
}
