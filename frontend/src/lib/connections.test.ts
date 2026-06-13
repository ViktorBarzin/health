import { describe, expect, it } from 'vitest';
import {
  canSubmitToken,
  canSync,
  lastSyncSummary,
  statusLabel,
} from './connections';
import type { ConnectionProviderInfo } from './types';

// Pure view-logic for the Connections settings UI (BYOT integrations, ADR-0006):
// the status label/tone, a relative "last synced" string, and the connect/sync
// action gates. No DOM, no fetch. Note the token is write-only and never part of
// a view model — there is nothing token-shaped to test here, by design.

function info(over: Partial<ConnectionProviderInfo> = {}): ConnectionProviderInfo {
  return {
    provider: 'oura',
    label: 'Oura Ring',
    description: '',
    instructions_url: 'https://cloud.ouraring.com/personal-access-tokens',
    token_based: true,
    connected: false,
    status: null,
    last_sync_at: null,
    last_error: null,
    ...over,
  };
}

describe('statusLabel', () => {
  it('shows "Not connected" when disconnected', () => {
    expect(statusLabel(info({ connected: false }))).toEqual({
      text: 'Not connected',
      tone: 'idle',
    });
  });

  it('shows "Connected" with a success tone when active', () => {
    expect(statusLabel(info({ connected: true, status: 'active' }))).toEqual({
      text: 'Connected',
      tone: 'success',
    });
  });

  it('shows "Needs attention" with an error tone when in error', () => {
    expect(statusLabel(info({ connected: true, status: 'error' }))).toEqual({
      text: 'Needs attention',
      tone: 'error',
    });
  });

  it('shows "Paused" when disabled', () => {
    expect(statusLabel(info({ connected: true, status: 'disabled' }))).toEqual({
      text: 'Paused',
      tone: 'muted',
    });
  });
});

describe('lastSyncSummary', () => {
  const now = new Date('2026-06-12T12:00:00Z');

  it('reports "Never synced" with no timestamp', () => {
    expect(lastSyncSummary(null, now)).toBe('Never synced');
  });

  it('reports "just now" for a very recent sync', () => {
    expect(lastSyncSummary('2026-06-12T11:59:40Z', now)).toBe('just now');
  });

  it('reports minutes', () => {
    expect(lastSyncSummary('2026-06-12T11:55:00Z', now)).toBe('5 min ago');
  });

  it('reports hours', () => {
    expect(lastSyncSummary('2026-06-12T09:00:00Z', now)).toBe('3 hr ago');
  });

  it('reports days, singular and plural', () => {
    expect(lastSyncSummary('2026-06-11T12:00:00Z', now)).toBe('1 day ago');
    expect(lastSyncSummary('2026-06-10T12:00:00Z', now)).toBe('2 days ago');
  });

  it('handles an unparseable timestamp gracefully', () => {
    expect(lastSyncSummary('not-a-date', now)).toBe('Never synced');
  });
});

describe('canSync', () => {
  it('is true only when connected and not busy', () => {
    expect(canSync(info({ connected: true }), false)).toBe(true);
    expect(canSync(info({ connected: true }), true)).toBe(false);
    expect(canSync(info({ connected: false }), false)).toBe(false);
  });
});

describe('canSubmitToken', () => {
  it('requires a non-blank token and not busy', () => {
    expect(canSubmitToken('abc', false)).toBe(true);
    expect(canSubmitToken('   ', false)).toBe(false);
    expect(canSubmitToken('', false)).toBe(false);
    expect(canSubmitToken('abc', true)).toBe(false);
  });
});
