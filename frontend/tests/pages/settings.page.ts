import { type Page, type Locator } from '@playwright/test';

export class SettingsPage {
  readonly page: Page;
  readonly importSection: Locator;
  readonly logoutBtn: Locator;

  // Upload component locators
  readonly uploadDropzone: Locator;
  readonly uploadBrowseBtn: Locator;
  readonly uploadFileInput: Locator;
  readonly uploadError: Locator;

  // Import status locators
  readonly importStatusCurrent: Locator;
  readonly importCancelBtn: Locator;

  constructor(page: Page) {
    this.page = page;
    this.importSection = page.locator('[data-testid="settings-import-section"]');
    this.logoutBtn = page.locator('[data-testid="settings-logout-btn"]');

    // Upload component
    this.uploadDropzone = page.locator('[data-testid="upload-dropzone"]');
    this.uploadBrowseBtn = page.locator('[data-testid="upload-browse-btn"]');
    this.uploadFileInput = page.locator('[data-testid="upload-file-input"]');
    this.uploadError = page.locator('[data-testid="upload-error"]');

    // Import status
    this.importStatusCurrent = page.locator('[data-testid="import-status-current"]');
    this.importCancelBtn = page.locator('[data-testid="import-cancel-btn"]');
  }

  async goto() {
    await this.page.goto('/settings');
  }

  importHistory(index: number): Locator {
    return this.page.locator(`[data-testid="import-history-${index}"]`);
  }

  importDeleteBtn(batchId: string): Locator {
    return this.page.locator(`[data-testid="import-delete-btn-${batchId}"]`);
  }
}
