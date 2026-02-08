import { api, ApiError } from '$lib/api';
import { startAuthentication, startRegistration } from '$lib/webauthn';
import type { User } from '$lib/types';

function createAuthStore() {
  let user = $state<User | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function checkAuth() {
    loading = true;
    error = null;
    try {
      user = await api.get<User>('/api/auth/me');
    } catch (e) {
      user = null;
    } finally {
      loading = false;
    }
  }

  async function login() {
    error = null;
    try {
      // Step 1: Get authentication options (no email needed -- discoverable credentials)
      const beginResp = await api.post<{ challenge_id: string; options: Record<string, unknown> }>('/api/auth/login/begin');

      // Step 2: Prompt browser for passkey
      const credential = await startAuthentication(beginResp.options);

      // Step 3: Send credential to server for verification
      user = await api.post<User>('/api/auth/login/complete', {
        challenge_id: beginResp.challenge_id,
        credential,
      });
    } catch (e) {
      if (e instanceof ApiError) {
        error = e.message;
      } else if (e instanceof Error) {
        error = e.message;
      } else {
        error = 'An unexpected error occurred';
      }
      throw e;
    }
  }

  async function register(email: string) {
    error = null;
    try {
      // Step 1: Get registration options from server
      const beginResp = await api.post<{ options: Record<string, unknown> }>('/api/auth/register/begin', { email });

      // Step 2: Prompt browser for passkey creation
      const credential = await startRegistration(beginResp.options);

      // Step 3: Send credential to server for verification and storage
      user = await api.post<User>('/api/auth/register/complete', { email, credential });
    } catch (e) {
      if (e instanceof ApiError) {
        error = e.message;
      } else if (e instanceof Error) {
        error = e.message;
      } else {
        error = 'An unexpected error occurred';
      }
      throw e;
    }
  }

  async function logout() {
    try {
      await api.post('/api/auth/logout');
    } catch {
      // ignore errors on logout
    }
    user = null;
  }

  return {
    get user() { return user; },
    get loading() { return loading; },
    get error() { return error; },
    checkAuth,
    login,
    register,
    logout,
  };
}

export const auth = createAuthStore();
