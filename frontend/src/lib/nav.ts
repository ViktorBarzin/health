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
  // The core action of the app (Fitbod replacement): log a live gym Session.
  // Pinned high in the thumb zone — '/sessions' is the list, '/sessions/new'
  // starts one.
  { href: '/sessions', label: 'Train', icon: 'M6.115 5.19l.319 1.913A6 6 0 008.11 10.36L9.75 12l-.387.775c-.217.433-.132.956.21 1.298l1.348 1.348c.21.21.329.497.329.795v1.089c0 .426.24.815.622 1.006l.153.076c.433.217.956.132 1.298-.21l.723-.723a8.7 8.7 0 002.288-4.042 1.087 1.087 0 00-.358-1.099l-1.33-1.108c-.251-.21-.582-.299-.905-.245l-1.17.195a1.125 1.125 0 01-.98-.314l-.295-.295a1.125 1.125 0 010-1.591l.13-.132a1.125 1.125 0 011.3-.21l.603.302a.809.809 0 001.086-1.086L14.25 7.5l1.256-.837a4.5 4.5 0 001.528-1.732l.146-.292M6.115 5.19A9 9 0 1017.18 4.64M6.115 5.19A8.965 8.965 0 0112 3c1.929 0 3.716.607 5.18 1.64' },
  { href: '/workouts', label: 'Workouts', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
  { href: '/exercises', label: 'Exercises', icon: 'M6.75 6.75v10.5m10.5-10.5v10.5M4.5 9.75h2.25m10.5 0H19.5M4.5 14.25h2.25m10.5 0H19.5M6.75 12h10.5' },
  { href: '/metrics', label: 'Metrics', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
  // Goal-driven Programs (#13, ADR-0004): the guided quiz, preset catalog and
  // the active Program overview. In the "More" sheet next to Train/Progress.
  { href: '/programs', label: 'Programs', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4' },
  // Training analytics (#10): per-muscle Recovery + volume heatmap and e1RM
  // strength trends. Lives in the "More" sheet alongside the other insights.
  { href: '/analytics', label: 'Progress', icon: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z' },
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
