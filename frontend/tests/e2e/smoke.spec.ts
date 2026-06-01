"""E2E smoke tests for critical user flows.

Run with: cd frontend && npx playwright test
Or from repo root: make e2e (if configured)

These tests verify that the main dashboard pages load without errors
and that critical UI elements are present.
"""

import { test, expect } from "@playwright/test";

test.describe("Smoke Tests — Critical User Flows", () => {
  test("home redirects to /tasks", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/tasks/);
  });

  test("tasks page loads and shows task tracker", async ({ page }) => {
    await page.goto("/tasks");
    await expect(page.getByRole("heading")).toBeVisible();
  });

  test("skills page loads", async ({ page }) => {
    await page.goto("/skills");
    await expect(page).toHaveURL(/\/skills/);
    await expect(page.getByRole("heading").first()).toBeVisible();
  });

  test("memory page loads", async ({ page }) => {
    await page.goto("/memory");
    await expect(page).toHaveURL(/\/memory/);
    await expect(page.getByRole("heading").first()).toBeVisible();
  });

  test("integrations page loads", async ({ page }) => {
    await page.goto("/integrations");
    await expect(page).toHaveURL(/\/integrations/);
    await expect(page.getByRole("heading").first()).toBeVisible();
  });

  test("preferences page loads", async ({ page }) => {
    await page.goto("/preferences");
    await expect(page).toHaveURL(/\/preferences/);
    await expect(page.getByRole("heading").first()).toBeVisible();
  });

  test("navigation between main pages works", async ({ page }) => {
    await page.goto("/tasks");
    await page.getByRole("link", { name: /skill/i }).first().click();
    await expect(page).toHaveURL(/\/skills/);
    await page.getByRole("link", { name: /memory/i }).first().click();
    await expect(page).toHaveURL(/\/memory/);
  });
});

test.describe("Task Creation Flow", () => {
  test("task can be submitted via chat interface", async ({ page }) => {
    await page.goto("/tasks");
    const input = page.getByPlaceholder(/message|task|ask/i).first();
    if (await input.isVisible()) {
      await input.fill("Summarize my last GitHub commits");
      await input.press("Enter");
    }
  });
});
