import { api } from '$lib/api';
import type { User } from '$lib/types';

/**
 * Current-user state.
 *
 * Identity is established at the edge by Authentik forward-auth (ADR-0003); the
 * app does not log in or out. This store just reflects who the backend resolved
 * the request to, via `/api/auth/me`.
 */
function createAuthStore() {
  let user = $state<User | null>(null);
  let loading = $state(true);

  async function checkAuth() {
    loading = true;
    try {
      user = await api.get<User>('/api/auth/me');
    } catch {
      user = null;
    } finally {
      loading = false;
    }
  }

  return {
    get user() {
      return user;
    },
    get loading() {
      return loading;
    },
    checkAuth,
  };
}

export const auth = createAuthStore();
