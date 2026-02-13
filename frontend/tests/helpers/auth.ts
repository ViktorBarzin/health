import { Page } from '@playwright/test';

const TEST_USER_EMAIL = 'e2e-test@example.com';

export async function loginAsTestUser(page: Page): Promise<void> {
  const baseURL = page.context()._options?.baseURL || 'http://localhost:8080';

  const response = await page.request.post(`${baseURL}/api/auth/test-login`, {
    data: { email: TEST_USER_EMAIL },
  });

  if (!response.ok()) {
    throw new Error(`Test login failed: ${response.status()} ${await response.text()}`);
  }
}

export { TEST_USER_EMAIL };
