import Link from "next/link";

/** Readbit brand mark: a stylised "R" whose leg turns into a page, with a spark of curiosity. */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect width="64" height="64" rx="16" className="fill-accent" />
      <path d="M18 17h14a10 10 0 0 1 0 20h-6l12 11" fill="none" stroke="white" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="45" cy="21" r="4" fill="#ffd166" />
    </svg>
  );
}

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 rounded-lg font-semibold tracking-tight text-ink" aria-label="Readbit home">
      <LogoMark />
      <span className="text-lg">Readbit</span>
    </Link>
  );
}
