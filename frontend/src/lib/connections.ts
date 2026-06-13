// Pure view-logic for the Connections settings UI (BYOT integrations, ADR-0006).
//
// No DOM, no fetch — just the client-side helpers the Connections section binds
// to: a human status label + tone, a "last synced" summary, and whether a
// connect/sync action is allowed. The token is NEVER part of any view model (it
// is write-only and never returned by the API). Mirrors lib/budget.ts's
// discipline; unit-tested in connections.test.ts.

import type { ConnectionProviderInfo, ConnectionStatus } from './types';

/** Visual tone for a connection status (drives the badge colour). */
export type StatusTone = 'idle' | 'success' | 'error' | 'muted';

/** A human label + tone for a provider's connection state. */
export function statusLabel(
  info: Pick<ConnectionProviderInfo, 'connected' | 'status'>,
): { text: string; tone: StatusTone } {
  if (!info.connected) {
    return { text: 'Not connected', tone: 'idle' };
  }
  switch (info.status as ConnectionStatus) {
    case 'active':
      return { text: 'Connected', tone: 'success' };
    case 'error':
      return { text: 'Needs attention', tone: 'error' };
    case 'disabled':
      return { text: 'Paused', tone: 'muted' };
    default:
      return { text: 'Connected', tone: 'success' };
  }
}

/**
 * A short "last synced" summary. `now` is injected so the helper stays pure and
 * testable. Returns 'Never synced' when there's no successful sync yet, else a
 * coarse relative time ("just now" / "5 min ago" / "3 hr ago" / "2 days ago").
 */
export function lastSyncSummary(lastSyncAt: string | null, now: Date = new Date()): string {
  if (!lastSyncAt) return 'Never synced';
  const then = new Date(lastSyncAt).getTime();
  if (Number.isNaN(then)) return 'Never synced';
  const deltaMs = now.getTime() - then;
  if (deltaMs < 0) return 'just now';

  const min = Math.floor(deltaMs / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const days = Math.floor(hr / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

/** Whether the "Sync now" action should be enabled (connected, not mid-request). */
export function canSync(
  info: Pick<ConnectionProviderInfo, 'connected'>,
  busy: boolean,
): boolean {
  return info.connected && !busy;
}

/** Whether the connect submit should be enabled (a non-blank token, not busy). */
export function canSubmitToken(token: string, busy: boolean): boolean {
  return token.trim().length > 0 && !busy;
}
