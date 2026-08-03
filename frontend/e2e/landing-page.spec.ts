import { test, expect } from '@playwright/test';

test.describe('VoxQuery Landing Page E2E', () => {
  test('renders hero, demo, and feature sections', async ({ page }) => {
    await page.goto('http://localhost:3000/');
    await page.waitForLoadState('networkidle');

    // Hero
    await expect(page.getByRole('heading', { level: 1, name: /ask your data/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /sign in to voxquery/i }).first()).toBeVisible();

    // How it works
    await expect(page.getByRole('heading', { name: 'Speak' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Understand' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Insight' })).toBeVisible();

    // Feature grid
    await expect(page.getByRole('heading', { name: 'Executive briefings' })).toBeVisible();

    await page.screenshot({ path: 'artifacts/landing-page.png', fullPage: true });
  });

  test('sign in from the landing page reaches the workspace', async ({ page }) => {
    await page.goto('http://localhost:3000/');
    await page.waitForLoadState('networkidle');

    await page.getByRole('link', { name: /sign in to voxquery/i }).first().click();
    await page.waitForURL('**/app');
    await expect(page.getByRole('heading', { name: /What would you like to know\?/i })).toBeVisible();
  });

  test('desktop screenshot at 1440x900', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('http://localhost:3000/');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: 'artifacts/landing-desktop-1440x900.png', fullPage: true });
  });

  test('mobile screenshot at 390x844', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('http://localhost:3000/');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: 'artifacts/landing-mobile-390x844.png', fullPage: true });
  });
});
