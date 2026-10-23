import type { ThemeTokens } from '../types';

export type ResolvedTheme = Required<ThemeTokens>;

/** Default tokens, matched to the Care assistant prototype. Portals override per theme. */
export const DEFAULT_THEME: ResolvedTheme = {
  brand: '#1f6b57',
  brandStrong: '#17574a',
  brandSoft: '#e6f1ec',
  brandContrast: '#ffffff',
  surface: '#ffffff',
  surfaceAlt: '#f5f5f2',
  surfaceSunken: '#eeefec',
  border: '#dcdfdb',
  borderStrong: '#c4c9c4',
  text: '#1b1f1d',
  textMuted: '#5f6964',
  good: '#1d7550',
  warning: '#8a5a00',
  attention: '#b42318',
  radius: '10px',
  fontFamily: "'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif",
};

/** Named presets selectable with the `theme` attribute. */
export const THEME_PRESETS: Record<string, ThemeTokens> = {
  default: {},
  'member-portal': {},
  'provider-portal': {},
};

/** A token value may not break out of its declaration (no `;`, braces, angle brackets or comments). */
const SAFE_VALUE = /^[^;{}<>\\]*$/;

export function resolveTheme(preset: string | null | undefined, overrides: ThemeTokens | undefined): ResolvedTheme {
  const merged: ResolvedTheme = { ...DEFAULT_THEME, ...(THEME_PRESETS[preset ?? 'default'] ?? {}) };
  for (const [key, value] of Object.entries(overrides ?? {}) as Array<[keyof ThemeTokens, unknown]>) {
    if (!(key in DEFAULT_THEME)) continue;
    if (typeof value === 'string' && value.trim() && SAFE_VALUE.test(value) && !value.includes('/*')) merged[key] = value.trim();
    else console.warn(`[agent-widget] ignoring invalid theme token "${key}"`);
  }
  return merged;
}

const VAR_NAMES: Record<keyof ThemeTokens, string> = {
  brand: '--aw-brand',
  brandStrong: '--aw-brand-strong',
  brandSoft: '--aw-brand-soft',
  brandContrast: '--aw-brand-contrast',
  surface: '--aw-surface',
  surfaceAlt: '--aw-surface-alt',
  surfaceSunken: '--aw-surface-sunken',
  border: '--aw-border',
  borderStrong: '--aw-border-strong',
  text: '--aw-text',
  textMuted: '--aw-text-muted',
  good: '--aw-good',
  warning: '--aw-warning',
  attention: '--aw-attention',
  radius: '--aw-radius',
  fontFamily: '--aw-font',
};

/**
 * Theme tokens become CSS custom properties on :host. Page styles win over :host rules, so a portal
 * can also override any token from its own stylesheet: `agent-widget { --aw-brand: #0b5cad; }`.
 */
export function themeToCss(theme: ResolvedTheme): string {
  const lines = (Object.keys(VAR_NAMES) as Array<keyof ThemeTokens>).map((key) => `${VAR_NAMES[key]}: ${theme[key]};`);
  return `:host { ${lines.join(' ')} }`;
}
