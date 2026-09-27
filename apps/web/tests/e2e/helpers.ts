import { expect, type Page } from "@playwright/test";
import path from "path";

export const FIXTURES = path.resolve(__dirname, "../../../../evals/fixtures");

export async function startGuest(page: Page) {
  await page.goto("/start");
  await page.getByTestId("privacy-ack").check();
  await page.getByTestId("continue-guest").click();
  await page.waitForURL("**/app");
}

export async function register(page: Page, email: string, password = "correct-horse-42") {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/app");
}

export async function uploadAndOpen(page: Page, file: string) {
  await page.goto("/app/upload");
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, file));
  await expect(page.getByTestId("upload-progress")).toBeVisible();
  await page.getByTestId("open-book").click({ timeout: 60_000 });
  await page.waitForURL(/\/app\/books\/[0-9a-f-]+$/);
  return page.url().split("/").pop()!;
}

/**
 * Deterministic answer oracle for the offline engine's verbatim questions, built only from information the
 * reader can also see (the question, its options and the chapter's source text). Never reads the answer key.
 */
export async function correctOption(page: Page, bookId: string): Promise<string> {
  const q = page.getByTestId("quiz-question");
  const stem = (await q.locator("p").first().innerText()).trim();
  const options = await q.locator("label[data-testid^=option-]").all();
  const chapters = await (await page.request.get(`/api/v1/books/${bookId}/chapters`)).json();
  let source = "";
  for (const ch of chapters.items) {
    const res = await (await page.request.get(`/api/v1/books/${bookId}/chapters/${ch.id}/passages`)).json();
    source += " " + res.items.map((p: { text: string }) => p.text).join(" ");
  }
  const norm = (s: string) => s.toLowerCase().replace(/[“”"'’]/g, "").replace(/\s+/g, " ").trim();
  const text = norm(source);
  const quoted = stem.match(/“(.*)”/)?.[1];
  for (const opt of options) {
    const key = (await opt.getAttribute("data-testid"))!.replace("option-", "");
    const optText = (await opt.locator("span").nth(1).innerText()).trim();
    const candidate = quoted && quoted.includes("_____") ? quoted.replace("_____", optText) : optText;
    if (text.includes(norm(candidate))) return key;
  }
  throw new Error("oracle could not determine the supported option");
}
