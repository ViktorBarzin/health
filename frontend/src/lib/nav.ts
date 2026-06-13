// Shared navigation model for the app shell (ADR-0007: phone-first).
//
// Both the desktop Sidebar and the mobile BottomNav render from this single
// source of truth so the two surfaces never drift. The bottom bar shows the
// first `MOBILE_PRIMARY_COUNT` items as tabs; the rest live behind a "More"
// sheet so every page stays reachable on a phone.

export interface NavItem {
  href: string;
  label: string;
  /** Heroicons-style outline path data (24x24 viewBox). */
  icon: string;
}

export const NAV_ITEMS: NavItem[] = [
  { href: '/', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { href: '/workouts', label: 'Workouts', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
  { href: '/metrics', label: 'Metrics', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
  { href: '/trends', label: 'Trends', icon: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6' },
  { href: '/sleep', label: 'Sleep', icon: 'M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z' },
  { href: '/body', label: 'Body', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
  { href: '/settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
];

/** Number of items pinned as tabs in the mobile bottom bar (rest go to "More"). */
export const MOBILE_PRIMARY_COUNT = 4;

export const MOBILE_PRIMARY: NavItem[] = NAV_ITEMS.slice(0, MOBILE_PRIMARY_COUNT);
export const MOBILE_OVERFLOW: NavItem[] = NAV_ITEMS.slice(MOBILE_PRIMARY_COUNT);

/**
 * Whether `href` is the active nav target for the current `pathname`.
 *
 * The dashboard ('/') only matches exactly; every other item matches its
 * subtree (e.g. '/workouts' is active on '/workouts/abc'). Trailing slashes on
 * the current path are tolerated.
 */
export function isActive(href: string, pathname: string): boolean {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (href === '/') return path === '/';
  return path === href || path.startsWith(href + '/');
}

/**
 * Whether the "More" overflow entry should render as active — true when the
 * current path matches any overflow item (so the tab highlights while you're on
 * a page that lives behind it).
 */
export function isOverflowActive(pathname: string): boolean {
  return MOBILE_OVERFLOW.some((item) => isActive(item.href, pathname));
}
