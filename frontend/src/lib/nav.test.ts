import { describe, expect, it } from 'vitest';
import {
  MORE_GROUPS,
  MORE_LINKS,
  PRIMARY_TABS,
  activeTab,
  isActive,
  isMoreActive,
  tabIsActive,
} from './nav';

describe('isActive', () => {
  it('matches Today only on the exact root path', () => {
    expect(isActive('/', '/')).toBe(true);
    expect(isActive('/', '/sessions')).toBe(false);
    expect(isActive('/', '/metrics/steps')).toBe(false);
  });

  it('matches a section on its own path and nested subtree', () => {
    expect(isActive('/sessions', '/sessions')).toBe(true);
    expect(isActive('/sessions', '/sessions/abc-123')).toBe(true);
    expect(isActive('/metrics', '/metrics/heart_rate')).toBe(true);
  });

  it('does not match a sibling that merely shares a prefix', () => {
    expect(isActive('/body', '/bodyweight')).toBe(false);
  });

  it('tolerates a trailing slash on the current path', () => {
    expect(isActive('/sessions', '/sessions/')).toBe(true);
    expect(isActive('/', '/')).toBe(true);
  });
});

describe('tabIsActive — aggregated sections', () => {
  const tab = (href: string) => PRIMARY_TABS.find((t) => t.href === href)!;

  it('lights Train across Sessions/Programs/Exercises/Workouts', () => {
    const train = tab('/sessions');
    for (const p of [
      '/sessions',
      '/sessions/new',
      '/sessions/abc-123',
      '/programs',
      '/programs/quiz',
      '/exercises',
      '/exercises/xyz',
      '/workouts',
      '/workouts/123',
    ]) {
      expect(tabIsActive(train, p)).toBe(true);
    }
  });

  it('lights Progress across Metrics/Trends/Body/Sleep/Analytics', () => {
    const progress = tab('/progress');
    for (const p of [
      '/progress',
      '/metrics',
      '/metrics/heart_rate',
      '/trends',
      '/body',
      '/sleep',
      '/analytics',
    ]) {
      expect(tabIsActive(progress, p)).toBe(true);
    }
  });

  it('lights Today only on the root, Nutrition on its subtree', () => {
    expect(tabIsActive(tab('/'), '/')).toBe(true);
    expect(tabIsActive(tab('/'), '/sessions')).toBe(false);
    expect(tabIsActive(tab('/nutrition'), '/nutrition/history')).toBe(true);
  });

  it('never lights two tabs for the same path', () => {
    for (const p of ['/', '/sessions/1', '/programs', '/nutrition', '/metrics/x', '/body']) {
      const lit = PRIMARY_TABS.filter((t) => tabIsActive(t, p));
      expect(lit.length).toBe(1);
    }
  });
});

describe('activeTab', () => {
  it('resolves the owning tab', () => {
    expect(activeTab('/')?.label).toBe('Today');
    expect(activeTab('/programs/quiz')?.label).toBe('Train');
    expect(activeTab('/sleep')?.label).toBe('Progress');
  });

  it('is undefined for a More-only route', () => {
    expect(activeTab('/settings')).toBeUndefined();
  });
});

describe('isMoreActive', () => {
  it('is true only when no primary tab owns the route', () => {
    expect(isMoreActive('/settings')).toBe(true);
  });

  it('is false on any primary-owned route, including aggregated ones', () => {
    for (const p of ['/', '/sessions/1', '/programs', '/nutrition', '/metrics/x', '/analytics']) {
      expect(isMoreActive(p)).toBe(false);
    }
  });
});

describe('shell structure', () => {
  it('exposes the five-tab IA: Today · Train · Nutrition · Progress', () => {
    expect(PRIMARY_TABS.map((t) => t.label)).toEqual(['Today', 'Train', 'Nutrition', 'Progress']);
    expect(PRIMARY_TABS[0].href).toBe('/');
    expect(PRIMARY_TABS.find((t) => t.label === 'Train')?.href).toBe('/sessions');
    expect(PRIMARY_TABS.find((t) => t.label === 'Nutrition')?.href).toBe('/nutrition');
  });

  it('every primary tab has a non-empty icon', () => {
    for (const t of PRIMARY_TABS) expect(t.icon.length).toBeGreaterThan(0);
  });

  it('the More sheet groups every secondary destination', () => {
    expect(MORE_GROUPS.map((g) => g.title)).toEqual(['Train', 'Progress', 'Account']);
    expect(MORE_LINKS).toEqual(MORE_GROUPS.flatMap((g) => g.items));
  });

  it('keeps every app section reachable from a tab or the More sheet', () => {
    const sections = [
      '/',
      '/sessions',
      '/nutrition',
      '/progress',
      '/programs',
      '/exercises',
      '/workouts',
      '/metrics',
      '/trends',
      '/body',
      '/sleep',
      '/analytics',
      '/settings',
    ];
    const moreHrefs = new Set(MORE_LINKS.map((l) => l.href));
    for (const s of sections) {
      const viaTab = PRIMARY_TABS.some((t) => t.href === s);
      const viaMore = moreHrefs.has(s);
      expect(viaTab || viaMore, `${s} unreachable`).toBe(true);
    }
  });
});
