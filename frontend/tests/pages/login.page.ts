import { type Page, type Locator } from '@playwright/test';

export class LoginPage {
  readonly page: Page;
  readonly submitBtn: Locator;
  readonly error: Locator;
  readonly registerLink: Locator;

  constructor(page: Page) {
    this.page = page;
    this.submitBtn = page.locator('[data-testid="login-submit-btn"]');
    this.error = page.locator('[data-testid="login-error"]');
    this.registerLink = page.locator('[data-testid="login-register-link"]');
  }

  async goto() {
    await this.page.goto('/login');
  }
}
