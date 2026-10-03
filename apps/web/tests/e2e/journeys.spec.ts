import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import path from "path";
import { correctOption, FIXTURES, register, startGuest, uploadAndOpen } from "./helpers";

test("Journey A — guest summarization with citations, depth switch, bookmark and Q&A", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your next great read, in less time.");
  await page.getByRole("link", { name: "Start reading" }).first().click();
  await page.getByTestId("privacy-ack").check();
  await page.getByTestId("continue-guest").click();
  await page.waitForURL("**/app");
  await expect(page.getByText("Your library is empty")).toBeVisible();

  const bookId = await uploadAndOpen(page, "attentive_mind.pdf");
  await expect(page.getByTestId("book-title")).toHaveText("The Attentive Mind");
  await expect(page.getByTestId("toc").locator("li")).toHaveCount(4);

  await page.getByTestId("go-summarize").click();
  const view = page.getByTestId("summary-view");
  await expect(view).toBeVisible();
  await expect(view.getByText("Central thesis")).toBeVisible();
  const conciseCitations = await page.getByTestId("citation").count();
  expect(conciseCitations).toBeGreaterThan(0);

  await page.getByTestId("depth-comprehensive").click();
  await expect(page.getByTestId("depth-comprehensive")).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("summary-view")).toBeVisible();
  await expect(page.getByTestId("scope-select")).not.toHaveValue("book"); // still on the same chapter

  await page.getByTestId("citation").first().click();
  const popover = page.getByTestId("evidence-popover");
  await expect(popover).toContainText("Page");
  await popover.getByRole("link", { name: "Open in source" }).click();
  await page.waitForURL(/\/read\?chapter=.*&passage=/);
  await page.goBack();

  await page.getByTestId("summary-view").locator("section[data-section-key]").first().hover();
  await page.getByTestId("bookmark-btn").first().click();
  await expect(page.getByText("Saved")).toBeVisible();

  const qa = page.getByTestId("book-assistant");
  await qa.getByRole("textbox").fill("What is the testing effect?");
  await qa.getByRole("button", { name: "Ask" }).click();
  await expect(qa.getByTestId("qa-turn").first()).toContainText("recall");
  await expect(qa.getByTestId("qa-turn").first().getByTestId("citation").first()).toBeVisible();
  await qa.getByRole("textbox").fill("Who won the football world cup in 2010?");
  await qa.getByRole("button", { name: "Ask" }).click();
  await expect(qa.getByTestId("qa-abstain")).toContainText("Not in this book");

  await page.goto(`/app/books/${bookId}/notes`);
  await expect(page.getByTestId("annotation")).toHaveCount(1);
});

test("Journey B — registered library persists across refresh and sign-in", async ({ page }) => {
  await register(page, `lib-${Date.now()}@example.com`);
  const bookId = await uploadAndOpen(page, "backyard_compost.epub");
  await page.goto("/app/library");
  await expect(page.getByTestId("book-card")).toHaveCount(1);
  await page.reload();
  await expect(page.getByTestId("book-card")).toContainText("Backyard Compost");
  await page.goto(`/app/books/${bookId}/summary`);
  await expect(page.getByTestId("summary-view")).toBeVisible();

  const email = await page.evaluate(async () => (await (await fetch("/api/v1/me")).json()).user.email);
  await page.goto("/app/settings");
  await page.getByRole("main").getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("http://localhost:3001/");
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-42");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/app");
  await expect(page.getByTestId("book-card")).toContainText("Backyard Compost");
  await expect(page.getByText("Continue reading")).toBeVisible();
});

test("Journey C — adaptive lesson with feedback, completion, mastery and revision", async ({ page }) => {
  await startGuest(page);
  const bookId = await uploadAndOpen(page, "attentive_mind.pdf");
  await page.goto(`/app/books/${bookId}/learn`);
  await page.getByTestId("start-lesson-1").click();
  await expect(page.getByTestId("quiz-question")).toBeVisible();

  let answered = 0;
  while (answered < 10) {
    const q = page.getByTestId("quiz-question");
    await expect(q.locator("input[type=radio]")).toHaveCount(4);
    const right = await correctOption(page, bookId);
    const choice = answered === 1 ? ["A", "B", "C", "D"].find((k) => k !== right)! : right;
    await page.getByTestId(`option-${choice}`).click();
    await page.getByTestId("submit-answer").click();
    const fb = page.getByTestId("answer-feedback");
    await expect(fb).toContainText(answered === 1 ? "Not quite" : "Correct!");
    await expect(fb.getByTestId("correct-answer")).toContainText(right);
    await expect(fb.getByTestId("feedback-evidence").first()).toContainText("Supporting passage");
    await expect(q.locator("input[type=radio]").first()).toBeDisabled(); // selection is locked
    answered++;
    await page.getByTestId("next-question").click();
    if (await page.getByTestId("quiz-result").isVisible().catch(() => false)) break;
    await expect(page.getByTestId("quiz-question").or(page.getByTestId("quiz-result"))).toBeVisible();
    if (await page.getByTestId("quiz-result").isVisible()) break;
  }
  await expect(page.getByTestId("quiz-result")).toContainText(`You answered ${answered - 1} of ${answered} correctly.`);
  await page.getByRole("link", { name: "Back to lessons" }).click();
  await expect(page.getByTestId("lesson-list").locator("li").first()).toContainText("Completed");
  await expect(page.getByText("Topic mastery")).toBeVisible();
  await page.getByTestId("start-revision").click();
  await expect(page.getByTestId("quiz-question")).toBeVisible();
  await expect(page.getByText("Revise weak concepts")).toBeVisible();

  await page.goto("/app/learning");
  await expect(page.getByTestId("achievement-first_lesson")).toHaveAttribute("data-earned", "true");
});

test("Journey D — unsupported, malformed and retried uploads never become ready", async ({ page }) => {
  await startGuest(page);
  await page.goto("/app/upload");
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "notes.txt"));
  await expect(page.getByRole("alert").filter({ hasText: "PDF and EPUB" })).toBeVisible();

  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "malformed.pdf"));
  const failed = page.getByTestId("processing-failed");
  await expect(failed).toContainText("damaged");
  await failed.getByRole("button", { name: "Retry processing" }).click();
  await expect(page.getByTestId("processing-failed")).toBeVisible();
  await expect(page.getByTestId("open-book")).toHaveCount(0);

  await page.goto("/app/library");
  await expect(page.getByTestId("book-card")).toContainText("Failed");
  await page.getByTestId("book-card").getByRole("link").first().click();
  await expect(page.getByText("Summarizer")).toHaveAttribute("aria-disabled", "true");
});

test("Journey E — another user and another guest cannot access a book", async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  await register(a, `owner-${Date.now()}@example.com`);
  const bookId = await uploadAndOpen(a, "attentive_mind.pdf");
  const chapters = await (await a.request.get(`/api/v1/books/${bookId}/chapters`)).json();

  for (const kind of ["user", "guest"] as const) {
    const b = await (await browser.newContext()).newPage();
    if (kind === "user") await register(b, `intruder-${Date.now()}@example.com`);
    else await startGuest(b);
    await b.goto(`/app/books/${bookId}`);
    await expect(b.getByRole("alert").filter({ hasText: "Book not found" })).toBeVisible();
    for (const url of [`/api/v1/books/${bookId}`, `/api/v1/books/${bookId}/summaries`, `/api/v1/books/${bookId}/annotations`,
      `/api/v1/books/${bookId}/chapters/${chapters.items[0].id}/passages`, `/api/v1/books/${bookId}/progress`, `/api/v1/books/${bookId}/lessons`]) {
      expect((await b.request.get(url)).status(), url).toBe(404);
    }
    const post = await b.request.post(`/api/v1/books/${bookId}/questions`, { data: { question: "What?" }, headers: { "X-Readbit-CSRF": "1" } });
    expect(post.status()).toBe(404);
    const del = await b.request.delete(`/api/v1/books/${bookId}`, { headers: { "X-Readbit-CSRF": "1" } });
    expect(del.status()).toBe(404);
  }
  expect((await a.request.get(`/api/v1/books/${bookId}`)).status()).toBe(200);
});

test("Interface language switches to Hindi", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("language-select").selectOption("hi");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("आपकी अगली बेहतरीन किताब, कम समय में।");
  await expect(page.locator("html")).toHaveAttribute("lang", "hi");
  await page.getByTestId("language-select").selectOption("en");
});

test("Accessibility: no serious axe violations on key screens", async ({ page }) => {
  const check = async (name: string) => {
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
    expect(serious.map((v) => `${name}: ${v.id} (${v.nodes.length})`)).toEqual([]);
  };
  await page.goto("/");
  await check("landing");
  await startGuest(page);
  await check("dashboard");
  const bookId = await uploadAndOpen(page, "attentive_mind.pdf");
  await check("overview");
  await page.goto(`/app/books/${bookId}/summary`);
  await expect(page.getByTestId("summary-view")).toBeVisible();
  await check("summary");
  await page.goto(`/app/books/${bookId}/learn`);
  await page.getByTestId("start-lesson-1").click();
  await expect(page.getByTestId("quiz-question")).toBeVisible();
  await check("quiz");
});
