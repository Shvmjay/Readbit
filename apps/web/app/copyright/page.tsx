import { LegalPage } from "@/components/layout/LegalPage";
import { serverDictionary } from "@/lib/server-i18n";

export const metadata = { title: "Copyright" };
export default async function Copyright() {
  const { d } = await serverDictionary();
  return (
    <LegalPage d={d} title={d.legal.copyrightTitle}>
      <p>Readbit is a private reading and learning aid. Uploaded books are visible only to the person who uploaded them and are never shared or publicly indexed.</p>
      <h2>Safeguards</h2>
      <ul>
        <li>Original files are stored privately and are never exposed through public links.</li>
        <li>Source excerpts shown as citations are short and limited in length.</li>
        <li>Summaries are designed to be transformative study aids and do not reproduce books in full.</li>
      </ul>
      <h2>Reporting</h2>
      <p>If you believe content on Readbit infringes your copyright, contact copyright@readbit.example with the details of the work and the content concerned.</p>
    </LegalPage>
  );
}
