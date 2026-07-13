// Navigation model — the single source of truth for the app shell (ADR-0007
// phone-first, ADR-0008 IA rework).
//
// Five primary destinations sit in the thumb zone: Today · Train · Nutrition ·
// Progress · More. Four are route tabs; "More" is a sheet. Each tab OWNS a set
// of routes (its href subtree plus any `match` prefixes) so the right tab stays
// lit across an aggregated area — Train spans Sessions/Programs/Exercises/
// Workouts, Progress spans Metrics/Trends/Body/Sleep/Analytics. The desktop
// Sidebar and the mobile BottomNav both render from this file so they never
// drift.

export interface NavTab {
  /** Primary destination for the tab. */
  href: string;
  label: string;
  /** Heroicons-style outline path data (24×24 viewBox). */
  icon: string;
  /** Extra route prefixes (besides the href subtree) that light this tab. */
  match?: string[];
}

export interface NavLink {
  href: string;
  label: string;
  icon: string;
}

export interface NavGroup {
  title: string;
  items: NavLink[];
}

const ICON = {
  today:
    'M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z',
  train: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z',
  nutrition:
    'M3 3v6.75A2.25 2.25 0 005.25 12H6m0-9v18m0-9h.75A2.25 2.25 0 009 9.75V3M15 3c-1.243 0-2.25 1.612-2.25 3.6 0 1.658.7 3.052 1.65 3.464.37.16.6.534.6.936V21m3-18v18',
  progress:
    'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
  more: 'M6.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM12.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM18.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0z',
  programs:
    'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
  exercises:
    'M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 8.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z',
  workouts:
    'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z',
  metrics:
    'M3.75 3v11.25A2.25 2.25 0 006 16.5h12M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5m-12 0v3.75m0-3.75h12m0 0v3.75M9 11.25l2.25-2.25 2.25 2.25L18 6.75',
  trends: 'M2.25 18 9 11.25l3.75 3.75L21.75 6M21.75 6h-4.5m4.5 0v4.5',
  body: 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z',
  sleep:
    'M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z',
  analytics: 'M10.5 6a7.5 7.5 0 107.5 7.5h-7.5V6zM13.5 3a7.5 7.5 0 017.5 7.5h-7.5V3z',
  settings:
    'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281zM15 12a3 3 0 11-6 0 3 3 0 016 0z',
} as const;

export const PRIMARY_TABS: NavTab[] = [
  { href: '/', label: 'Today', icon: ICON.today },
  {
    href: '/sessions',
    label: 'Train',
    icon: ICON.train,
    match: ['/programs', '/exercises', '/workouts'],
  },
  { href: '/nutrition', label: 'Nutrition', icon: ICON.nutrition },
  {
    href: '/progress',
    label: 'Progress',
    icon: ICON.progress,
    match: ['/metrics', '/trends', '/body', '/sleep', '/analytics'],
  },
];

/** The "More" sheet — grouped launchers for every secondary destination. */
export const MORE_GROUPS: NavGroup[] = [
  {
    title: 'Train',
    items: [
      { href: '/programs', label: 'Programs', icon: ICON.programs },
      { href: '/exercises', label: 'Exercises', icon: ICON.exercises },
      { href: '/workouts', label: 'Workouts', icon: ICON.workouts },
    ],
  },
  {
    title: 'Progress',
    items: [
      { href: '/metrics', label: 'Metrics', icon: ICON.metrics },
      { href: '/trends', label: 'Trends', icon: ICON.trends },
      { href: '/body', label: 'Body', icon: ICON.body },
      { href: '/sleep', label: 'Sleep', icon: ICON.sleep },
      { href: '/analytics', label: 'Analytics', icon: ICON.analytics },
    ],
  },
  {
    title: 'Account',
    items: [{ href: '/settings', label: 'Settings', icon: ICON.settings }],
  },
];

/** Flattened More-sheet links (handy for iteration / reachability checks). */
export const MORE_LINKS: NavLink[] = MORE_GROUPS.flatMap((g) => g.items);

/** Icon for the "More" trigger itself. */
export const MORE_ICON = ICON.more;

/**
 * Whether `href` is the active target for `pathname`.
 *
 * '/' (Today) matches only the exact root; every other route matches its
 * subtree ('/sessions' lights on '/sessions/abc'). A trailing slash on the
 * current path is tolerated; a mere shared prefix ('/body' vs '/bodyweight')
 * does NOT match.
 */
export function isActive(href: string, pathname: string): boolean {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (href === '/') return path === '/';
  return path === href || path.startsWith(href + '/');
}

/** Whether a primary tab is active — its href subtree OR any `match` prefix. */
export function tabIsActive(tab: NavTab, pathname: string): boolean {
  if (isActive(tab.href, pathname)) return true;
  return (tab.match ?? []).some((prefix) => isActive(prefix, pathname));
}

/** The primary tab that owns `pathname`, if any. */
export function activeTab(pathname: string): NavTab | undefined {
  return PRIMARY_TABS.find((tab) => tabIsActive(tab, pathname));
}

/**
 * Whether the "More" entry should render active — true exactly when no primary
 * tab owns the current route (e.g. /settings), so the bar always highlights
 * precisely one slot.
 */
export function isMoreActive(pathname: string): boolean {
  return !PRIMARY_TABS.some((tab) => tabIsActive(tab, pathname));
}
