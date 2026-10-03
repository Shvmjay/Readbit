import { LegalPage } from "@/components/layout/LegalPage";
import { serverDictionary } from "@/lib/server-i18n";

export const metadata = { title: "Terms" };
export default async function Terms() {
  const { d } = await serverDictionary();
  return (
    <LegalPage d={d} title={d.legal.termsTitle}>
      <h2>Your uploads</h2>
      <p>Upload only books you have the right to use. Uploads are for your private, personal reading and learning. Do not use Readbit to redistribute or publish copyrighted works.</p>
      <h2>AI-generated content</h2>
      <p>Summaries, answers and quiz questions are generated automatically from your book. Readbit works to keep them faithful and cites its sources, but they can still contain mistakes. The original book is the authoritative source; Readbit does not replace it.</p>
      <h2>Acceptable use</h2>
      <p>Do not attempt to access other users’ content, disrupt the service or upload malicious files.</p>
      <h2>Availability</h2>
      <p>Readbit is an early-stage product provided as is. Features and limits may change.</p>
    </LegalPage>
  );
}
