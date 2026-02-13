import { type Page, type Locator } from '@playwright/test';

export class RegisterPage {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly submitBtn: Locator;
  readonly error: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailInput = page.locator('[data-testid="register-email-input"]');
    this.submitBtn = page.locator('[data-testid="register-submit-btn"]');
    this.error = page.locator('[data-testid="register-error"]');
  }

  async goto() {
    await this.page.goto('/register');
  }
}
