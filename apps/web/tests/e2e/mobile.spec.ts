import { expect, test } from "@playwright/test";
import { startGuest, uploadAndOpen } from "./helpers";

test("mobile: navigation, upload and summary work on a phone viewport", async ({ page }) => {
  await startGuest(page);
  const nav = page.getByRole("navigation", { name: "Main navigation" }).last();
  await expect(nav).toBeVisible();
  const bookId = await uploadAndOpen(page, "backyard_compost.epub");
  await page.goto(`/app/books/${bookId}/summary`);
  await expect(page.getByTestId("summary-view")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
});
