<script lang="ts">
  import { auth } from '$lib/stores/auth.svelte';
  import { goto } from '$app/navigation';

  let email = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;

    try {
      await auth.register(email);
      goto('/');
    } catch (err) {
      if (err instanceof Error) {
        error = err.message;
      } else {
        error = 'Registration failed. Please try again.';
      }
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen bg-surface-950 flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo -->
    <div class="flex flex-col items-center mb-8">
      <div class="w-14 h-14 rounded-2xl bg-primary-500 flex items-center justify-center mb-4">
        <svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
        </svg>
      </div>
      <h1 class="text-2xl font-bold text-surface-100">Create Account</h1>
      <p class="text-sm text-surface-500 mt-1">Get started with Health Dashboard</p>
    </div>

    <!-- Register form -->
    <div class="bg-surface-900 rounded-xl border border-surface-700 p-6">
      {#if error}
        <div class="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
          <p class="text-sm text-red-400">{error}</p>
        </div>
      {/if}

      <form onsubmit={handleSubmit} class="space-y-4">
        <div>
          <label for="email" class="block text-sm font-medium text-surface-300 mb-1.5">
            Email
          </label>
          <input
            id="email"
            type="email"
            bind:value={email}
            required
            placeholder="you@example.com"
            class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
                   text-surface-100 placeholder-surface-500 text-sm
                   focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
                   transition-colors"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          class="w-full py-2.5 px-4 bg-primary-500 hover:bg-primary-600 disabled:opacity-50
                 disabled:cursor-not-allowed text-white font-medium text-sm rounded-lg
                 transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
                 focus:ring-offset-surface-900"
        >
          {#if loading}
            <span class="flex items-center justify-center gap-2">
              <div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              Setting up passkey...
            </span>
          {:else}
            <span class="flex items-center justify-center gap-2">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
              </svg>
              Create account with passkey
            </span>
          {/if}
        </button>
      </form>
    </div>

    <!-- Login link -->
    <p class="text-center text-sm text-surface-500 mt-6">
      Already have an account?
      <a href="/login" class="text-primary-400 hover:text-primary-300 font-medium transition-colors">
        Sign in
      </a>
    </p>
  </div>
</div>
