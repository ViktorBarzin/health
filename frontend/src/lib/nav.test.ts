import { describe, expect, it } from 'vitest';
import {
  MOBILE_OVERFLOW,
  MOBILE_PRIMARY,
  MOBILE_PRIMARY_COUNT,
  NAV_ITEMS,
  isActive,
  isOverflowActive,
} from './nav';

describe('isActive', () => {
  it('matches the dashboard only on the exact root path', () => {
    expect(isActive('/', '/')).toBe(true);
    expect(isActive('/', '/workouts')).toBe(false);
    expect(isActive('/', '/metrics/steps')).toBe(false);
  });

  it('matches a section on its own path', () => {
    expect(isActive('/workouts', '/workouts')).toBe(true);
    expect(isActive('/metrics', '/metrics')).toBe(true);
  });

  it('matches a section on nested subtree paths', () => {
    expect(isActive('/workouts', '/workouts/abc-123')).toBe(true);
    expect(isActive('/metrics', '/metrics/heart_rate')).toBe(true);
  });

  it('does not match a sibling that merely shares a prefix', () => {
    // '/body' must not light up when on a hypothetical '/bodyweight' route.
    expect(isActive('/body', '/bodyweight')).toBe(false);
  });

  it('tolerates a trailing slash on the current path', () => {
    expect(isActive('/workouts', '/workouts/')).toBe(true);
    expect(isActive('/', '/')).toBe(true);
  });
});

describe('isOverflowActive', () => {
  it('is true when on a page behind the More sheet', () => {
    // Settings is an overflow item with the default split.
    expect(isOverflowActive('/settings')).toBe(true);
  });

  it('is false when on a primary tab', () => {
    expect(isOverflowActive('/')).toBe(false);
    expect(isOverflowActive('/workouts')).toBe(false);
  });
});

describe('mobile nav split', () => {
  it('partitions NAV_ITEMS into primary tabs and overflow with no gaps or overlap', () => {
    expect(MOBILE_PRIMARY).toHaveLength(MOBILE_PRIMARY_COUNT);
    expect([...MOBILE_PRIMARY, ...MOBILE_OVERFLOW]).toEqual(NAV_ITEMS);
  });

  it('keeps the dashboard as the first primary tab', () => {
    expect(MOBILE_PRIMARY[0]?.href).toBe('/');
  });

  it('every nav item is reachable from one of the two groups', () => {
    for (const item of NAV_ITEMS) {
      const inPrimary = MOBILE_PRIMARY.includes(item);
      const inOverflow = MOBILE_OVERFLOW.includes(item);
      expect(inPrimary || inOverflow).toBe(true);
    }
  });
});
