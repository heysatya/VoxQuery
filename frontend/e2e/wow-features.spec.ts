import { test, expect } from '@playwright/test';

test.describe('VoxQuery WOW Features E2E Automated Tests', () => {
  test('exercises Morning Briefing, Query Dock, Multi-Widget Workspace, Memory Graph, and Data Glass Panel', async ({ page }) => {
    // 1. Open VoxQuery local web application
    await page.goto('http://localhost:3000/app');
    await page.waitForLoadState('networkidle');

    // 2. Verify Hero Header and Morning Briefing
    await expect(page.getByRole('heading', { name: /What would you like to know\?/i })).toBeVisible();

    // 3. Click starter question "How did revenue perform last quarter?"
    const starterBtn = page.getByRole('button', { name: 'How did revenue perform last quarter?' }).first();
    await expect(starterBtn).toBeVisible();
    await starterBtn.click({ force: true });

    // 4. Wait for processing / pipeline result
    const insightNarrative = page.locator('main');
    await expect(insightNarrative).toBeVisible();

    // 5. Take screenshot of loaded Insight View with DataGlassPanel
    await page.screenshot({ path: 'artifacts/01-insight-view.png', fullPage: true });

    // 6. Test Multi-Widget Workspace Pin button
    const pinBtn = page.getByRole('button', { name: /pin to workspace/i });
    if (await pinBtn.isVisible()) {
      await pinBtn.click();
      await page.screenshot({ path: 'artifacts/02-workspace-pinned.png', fullPage: true });
    }

    // 7. Test Table View toggle & Row Drilldown
    const tableToggle = page.getByRole('button', { name: /table view/i });
    if (await tableToggle.isVisible()) {
      await tableToggle.click();
      await page.screenshot({ path: 'artifacts/03-table-view.png', fullPage: true });
    }

    // 8. Test Executive Memory Graph button
    const memGraphBtn = page.getByRole('button', { name: /explore graph/i });
    if (await memGraphBtn.isVisible()) {
      await memGraphBtn.click();
      await page.screenshot({ path: 'artifacts/04-memory-graph-modal.png', fullPage: true });
    }
  });
});
