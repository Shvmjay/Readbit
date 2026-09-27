import Link from "next/link";
import { serverDictionary } from "@/lib/server-i18n";

export default async function NotFound() {
  const { d } = await serverDictionary();
  return (
    <main id="main" className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-5xl font-semibold text-accent">404</p>
      <p className="text-muted">{d.common.notFound}</p>
      <Link href="/app" className="btn-primary">{d.common.goHome}</Link>
    </main>
  );
}
