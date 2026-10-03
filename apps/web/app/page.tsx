import Link from "next/link";
import { BookOpenCheck, BrainCircuit, FileUp, Link2, ShieldCheck, Eye, CheckCircle2, Quote } from "lucide-react";
import { PublicFooter, PublicHeader } from "@/components/layout/PublicChrome";
import { TrackView } from "@/components/layout/TrackView";
import { serverDictionary } from "@/lib/server-i18n";

export default async function Landing() {
  const { d } = await serverDictionary();
  const L = d.landing;
  const faqs = [[L.faq1Q, L.faq1A], [L.faq2Q, L.faq2A], [L.faq3Q, L.faq3A], [L.faq4Q, L.faq4A]];
  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">{d.nav.skip}</a>
      <TrackView name="landing_viewed" />
      <PublicHeader d={d} />
      <main id="main">
        {/* Hero */}
        <section className="relative overflow-hidden">
          <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_70%_0%,rgb(var(--accent)/0.12),transparent)]" />
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-[1.1fr_0.9fr] lg:pt-24">
            <div>
              <p className="eyebrow">{d.brand.tagline}</p>
              <h1 className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">{L.heroTitle}</h1>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted">{L.heroBody}</p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="/start" className="btn-primary px-6 py-3 text-base">{L.ctaStart}</Link>
                <a href="#how" className="btn-secondary px-6 py-3 text-base">{L.ctaHow}</a>
              </div>
            </div>
            <HeroPreview d={d} />
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="border-y border-line bg-surface/60 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <h2 className="text-3xl font-semibold">{L.howTitle}</h2>
            <ol className="mt-10 grid gap-6 md:grid-cols-3">
              {[[FileUp, L.how1Title, L.how1Body], [BookOpenCheck, L.how2Title, L.how2Body], [BrainCircuit, L.how3Title, L.how3Body]].map(([Icon, title, body], i) => {
                const I = Icon as typeof FileUp;
                return (
                  <li key={i} className="card p-6">
                    <div className="flex items-center gap-3">
                      <span className="rounded-xl bg-accent-soft p-2 text-accent"><I className="h-5 w-5" aria-hidden /></span>
                      <span className="text-sm font-semibold text-muted">0{i + 1}</span>
                    </div>
                    <h3 className="mt-4 text-lg font-semibold">{title as string}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted">{body as string}</p>
                  </li>
                );
              })}
            </ol>
          </div>
        </section>

        {/* Feature showcases */}
        <section className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2">
          <Feature title={L.sumTitle} body={L.sumBody} points={[L.sumPoint1, L.sumPoint2, L.sumPoint3]} icon={<Link2 className="h-5 w-5" aria-hidden />} />
          <Feature title={L.quizTitle} body={L.quizBody} points={[L.quizPoint1, L.quizPoint2, L.quizPoint3]} icon={<BrainCircuit className="h-5 w-5" aria-hidden />} />
        </section>

        {/* Example */}
        <section className="border-y border-line bg-surface/60 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <h2 className="text-3xl font-semibold">{L.exampleTitle}</h2>
            <p className="mt-2 text-sm text-muted">{L.exampleIntro}</p>
            <div className="mt-8 grid gap-5 lg:grid-cols-3">
              <div className="card bg-paper p-6">
                <p className="eyebrow">{L.exampleSource}</p>
                <p className="reading mt-3"><Quote className="mb-1 mr-1 inline h-4 w-4 text-muted" aria-hidden />{L.exampleSourceText}</p>
              </div>
              <div className="card p-6">
                <p className="eyebrow">{L.exampleSummary}</p>
                <p className="mt-3 leading-relaxed">{L.exampleSummaryText} <sup className="rounded bg-accent-soft px-1.5 py-0.5 text-[0.7rem] font-semibold text-accent">1</sup></p>
              </div>
              <div className="card p-6">
                <p className="eyebrow">{L.exampleQuiz}</p>
                <p className="mt-3 font-medium">{L.exampleQuizQ}</p>
                <ul className="mt-3 space-y-2 text-sm">
                  {[L.exampleQuizA, L.exampleQuizB, L.exampleQuizC, L.exampleQuizD].map((o, i) => (
                    <li key={o} className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${i === 0 ? "border-success/50 bg-success/10" : "border-line"}`}>
                      <span className="font-semibold text-muted">{"ABCD"[i]}</span> {o}
                      {i === 0 && <CheckCircle2 className="ml-auto h-4 w-4 text-success" aria-label="correct" />}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* Trust */}
        <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="text-3xl font-semibold">{L.trustTitle}</h2>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {[[ShieldCheck, L.trust1Title, L.trust1Body], [Link2, L.trust2Title, L.trust2Body], [Eye, L.trust3Title, L.trust3Body]].map(([Icon, title, body], i) => {
              const I = Icon as typeof ShieldCheck;
              return (
                <div key={i}>
                  <I className="h-6 w-6 text-accent" aria-hidden />
                  <h3 className="mt-3 font-semibold">{title as string}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{body as string}</p>
                </div>
              );
            })}
          </div>
        </section>

        {/* FAQ */}
        <section className="border-t border-line bg-surface/60 py-20">
          <div className="mx-auto max-w-3xl px-4 sm:px-6">
            <h2 className="text-3xl font-semibold">{L.faqTitle}</h2>
            <div className="mt-8 divide-y divide-line">
              {faqs.map(([q, a]) => (
                <details key={q} className="group py-4">
                  <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
                    {q}<span className="text-muted transition group-open:rotate-45" aria-hidden>+</span>
                  </summary>
                  <p className="mt-3 text-sm leading-relaxed text-muted">{a}</p>
                </details>
              ))}
            </div>
            <div className="mt-12 text-center">
              <Link href="/start" className="btn-primary px-6 py-3 text-base">{L.ctaStart}</Link>
            </div>
          </div>
        </section>
      </main>
      <PublicFooter d={d} />
    </>
  );
}

function Feature({ title, body, points, icon }: { title: string; body: string; points: string[]; icon: React.ReactNode }) {
  return (
    <div className="card p-8">
      <span className="inline-flex rounded-xl bg-accent-soft p-2 text-accent">{icon}</span>
      <h2 className="mt-4 text-2xl font-semibold">{title}</h2>
      <p className="mt-3 leading-relaxed text-muted">{body}</p>
      <ul className="mt-5 space-y-2 text-sm">
        {points.map((p) => (
          <li key={p} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />{p}</li>
        ))}
      </ul>
    </div>
  );
}

function HeroPreview({ d }: { d: Awaited<ReturnType<typeof serverDictionary>>["d"] }) {
  const L = d.landing;
  return (
    <div aria-hidden className="relative hidden pb-24 lg:block">
      <div className="card rotate-[-1.5deg] bg-paper p-6 pb-8">
        <p className="eyebrow">{d.summary.thesis}</p>
        <p className="reading mt-2 text-base">{L.exampleSummaryText}<sup className="ml-1 rounded bg-accent-soft px-1.5 text-[0.7rem] font-semibold text-accent">1</sup></p>
        <div className="mt-4 flex gap-2">
          <span className="chip">{d.summary.concise}</span><span className="chip border-accent/40 text-accent">{d.summary.balanced}</span><span className="chip">{d.summary.comprehensive}</span>
        </div>
      </div>
      <div className="card absolute bottom-0 right-0 w-[80%] rotate-[2deg] p-5 shadow-lift">
        <p className="text-sm font-medium">{L.exampleQuizQ}</p>
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-success/50 bg-success/10 px-3 py-2 text-sm">
          <CheckCircle2 className="h-4 w-4 text-success" /> {L.exampleQuizA}
        </div>
      </div>
    </div>
  );
}
