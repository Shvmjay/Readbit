import { LegalPage } from "@/components/layout/LegalPage";
import { serverDictionary } from "@/lib/server-i18n";

export const metadata = { title: "Privacy" };
export default async function Privacy() {
  const { d } = await serverDictionary();
  return (
    <LegalPage d={d} title={d.legal.privacyTitle}>
      <h2>What we store</h2>
      <ul>
        <li>The books you upload, in private storage that is never publicly accessible.</li>
        <li>Text extracted from your books, and summaries, answers and quiz questions generated from them.</li>
        <li>Your notes, highlights, bookmarks, reading position and quiz answers.</li>
        <li>For accounts: your email, a salted password hash (argon2id) and preferences. We never store your password.</li>
      </ul>
      <h2>How your books are used</h2>
      <p>Your book is used only to produce content for you. It is never shared, published or indexed, and it is never used to train or fine-tune AI models. When an external AI provider is configured, relevant passages are sent to that provider solely to generate your content, under terms that do not permit training on your data.</p>
      <h2>Retention and deletion</h2>
      <ul>
        <li>Guest sessions and their books are deleted automatically when the guest period ends.</li>
        <li>You can delete any book at any time; its file and everything derived from it are removed.</li>
        <li>You can delete your account from Settings; this removes your library, notes and progress.</li>
        <li>You can export your data (library metadata, notes and progress) from Settings.</li>
      </ul>
      <h2>Analytics</h2>
      <p>We record privacy-conscious product events (for example “quiz started”) with pseudonymous identifiers. Analytics never contain book text, your notes or the questions you ask.</p>
      <h2>Contact</h2>
      <p>Questions or requests: privacy@readbit.example.</p>
    </LegalPage>
  );
}
