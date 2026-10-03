import type { ReactNode } from "react";
import { PublicFooter, PublicHeader } from "./PublicChrome";
import type { Dictionary } from "@/lib/i18n";

export function LegalPage({ d, title, children }: { d: Dictionary; title: string; children: ReactNode }) {
  return (
    <>
      <PublicHeader d={d} />
      <main id="main" className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <h1 className="text-3xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-muted">MVP policy summary — last updated 27 September 2026. The English version is authoritative.</p>
        <div className="mt-8 space-y-6 leading-relaxed [&_h2]:mt-8 [&_h2]:text-xl [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_p]:text-ink/90">{children}</div>
      </main>
      <PublicFooter d={d} />
    </>
  );
}
