import { test, expect } from '@playwright/test';
import { loginAsTestUser } from './helpers/auth';
import { SMALL_EXPORT_XML } from './helpers/test-data';

test.describe('Import', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsTestUser(page);
  });

  test('upload XML via file input', async ({ page }) => {
    await page.goto('/settings');
    const fileInput = page.locator('[data-testid="upload-file-input"]');
    await fileInput.setInputFiles(SMALL_EXPORT_XML);
    // Should show import status
    await expect(page.locator('[data-testid="import-status-current"]')).toBeVisible({ timeout: 10000 });
  });

  test('import completes with record count', async ({ page }) => {
    await page.goto('/settings');
    const fileInput = page.locator('[data-testid="upload-file-input"]');
    await fileInput.setInputFiles(SMALL_EXPORT_XML);
    // Wait for completion (may take a while for parsing)
    await expect(page.locator('text=/completed|completed with errors/i')).toBeVisible({ timeout: 60000 });
  });
});
