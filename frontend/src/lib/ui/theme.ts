// Theme resolution (ADR-0008): dark by default, follows the OS, overridable.
//
// The actual light/dark values live in app.css and switch on
// `prefers-color-scheme` with ZERO JS — so the auto path needs nothing here.
// This module only handles an explicit user OVERRIDE: it stamps [data-theme]
// on <html> (which app.css keys off) and persists the choice. The resolver is
// pure; everything else guards SSR.

export type ThemePref = 'system' | 'light' | 'dark';
export type EffectiveTheme = 'light' | 'dark';

const STORAGE_KEY = 'theme-pref';

/** Pure: collapse a preference + the OS signal into the effective theme. */
export function resolveTheme(pref: ThemePref, systemPrefersDark: boolean): EffectiveTheme {
  if (pref === 'system') return systemPrefersDark ? 'dark' : 'light';
  return pref;
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return true;
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

/** Apply a preference: 'system' clears the override (CSS @media takes over). */
export function applyTheme(pref: ThemePref): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (pref === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', pref);
}

export function loadThemePref(): ThemePref {
  if (typeof localStorage === 'undefined') return 'system';
  const v = localStorage.getItem(STORAGE_KEY);
  return v === 'light' || v === 'dark' ? v : 'system';
}

export function setThemePref(pref: ThemePref): void {
  if (typeof localStorage !== 'undefined') {
    if (pref === 'system') localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, pref);
  }
  applyTheme(pref);
}

/** Restore the persisted override on boot (no-op for 'system'). */
export function initTheme(): EffectiveTheme {
  const pref = loadThemePref();
  applyTheme(pref);
  return resolveTheme(pref, systemPrefersDark());
}
