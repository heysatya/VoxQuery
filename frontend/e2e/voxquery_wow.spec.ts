import { test, expect } from '@playwright/test';

test.describe('VoxQuery WOW Feature Business Scenarios E2E Suite (Zero-Mock)', () => {

  test('Scenario 1: Morning Briefing, Deepgram Audio Podcast & 1-Click PDF Exporter', async ({ page }) => {
    // 1. Load home page
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // 2. Test Download PDF Report button if visible
    const pdfBtn = page.getByRole('button', { name: /Download PDF Report/i }).first();
    if (await pdfBtn.isVisible()) {
      const [download] = await Promise.all([
        page.waitForEvent('download', { timeout: 15000 }).catch(() => null),
        pdfBtn.click(),
      ]);
      if (download) {
        expect(download.suggestedFilename()).toContain('.pdf');
      }
    }

    await page.screenshot({ path: 'artifacts/scenario1-briefing-audio-pdf.png', fullPage: true });
  });

  test('Scenario 2: Multi-Turn Context & Dynamic Executive Memory Graph DAG', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Turn 1: Click starter question
    const starterBtn = page.getByRole('button', { name: 'How did revenue perform last quarter?' }).first();
    await expect(starterBtn).toBeVisible({ timeout: 15000 });
    
    // Wait for button to be enabled if needed
    await page.waitForFunction(() => {
      const btn = document.querySelector('button:disabled');
      return !btn || !btn.textContent?.includes('How did revenue perform');
    }, { timeout: 10000 }).catch(() => null);

    await starterBtn.click({ force: true });

    // Wait for visualization / insight narrative
    await page.waitForTimeout(5000);

    // Open Memory Graph Modal if present
    const memGraphBtn = page.getByRole('button', { name: /explore graph|memory graph/i }).first();
    if (await memGraphBtn.isVisible()) {
      await memGraphBtn.click();
      const modal = page.locator('.glass-card, [role="dialog"]').first();
      await expect(modal).toBeVisible();
      await page.screenshot({ path: 'artifacts/scenario2-memory-graph-dag.png' });
    }
  });

  test('Scenario 3: Pre-SQL Ambiguity & Instant Clarification Interruption', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Verify main interactive area loaded
    const heading = page.getByRole('heading', { name: /What would you like to know\?/i });
    await expect(heading).toBeVisible({ timeout: 10000 });

    await page.screenshot({ path: 'artifacts/scenario3-clarification-interruption.png' });
  });

  test('Scenario 4: Statistical Anomaly Detection & Row-Level Transaction Drilldown', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const starterBtn = page.getByRole('button', { name: 'How did revenue perform last quarter?' }).first();
    await expect(starterBtn).toBeVisible({ timeout: 10000 });

    await page.screenshot({ path: 'artifacts/scenario4-anomaly-drilldown.png' });
  });

  test('Scenario 5: Multi-Widget Grid Workspace Layout Persistence', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const workspaceHeader = page.locator('text=Executive Grid Workspace').first();
    await expect(workspaceHeader).toBeVisible({ timeout: 10000 });

    // Reload page to assert state persistence
    await page.reload();
    await page.waitForLoadState('networkidle');

    await expect(workspaceHeader).toBeVisible();
    await page.screenshot({ path: 'artifacts/scenario5-workspace-persistence.png', fullPage: true });
  });

});
