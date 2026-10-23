/**
 * Client-side policy checks. These are defence in depth only: APIM / OPA remain the
 * authority. They stop a misbehaving agent from steering the portal somewhere unexpected.
 */

/** Matches a route against an allowlist. Entries may end with `*` for prefix match. */
export function isRouteAllowed(route: string, allowed: readonly string[] | undefined): boolean {
  if (!route.startsWith('/') || route.startsWith('//')) return false; // only same-origin portal routes
  if (!allowed || allowed.length === 0) return false;
  const path = route.split(/[?#]/)[0];
  return allowed.some((pattern) => {
    if (pattern === '*') return true;
    if (pattern.endsWith('*')) return path.startsWith(pattern.slice(0, -1));
    return path === pattern;
  });
}

/** Allows https URLs whose origin is listed, or the page's own origin. */
export function isUrlAllowed(url: string, allowedOrigins: readonly string[] | undefined, pageOrigin: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url, pageOrigin);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'https:' && parsed.origin !== pageOrigin) return false;
  if (parsed.origin === pageOrigin) return true;
  return (allowedOrigins ?? []).some((origin) => {
    try {
      return new URL(origin).origin === parsed.origin;
    } catch {
      return false;
    }
  });
}

/**
 * Extracts non-PHI references from action data for the host `action` event:
 * string values whose key ends in `Id` or `Ref` and look like opaque ids.
 */
export function extractRefs(data: Record<string, unknown> | undefined): Record<string, string> {
  const refs: Record<string, string> = {};
  if (!data) return refs;
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === 'string' && /(Id|Ref)$/.test(key) && /^[A-Za-z0-9_\-:.]{1,64}$/.test(value)) {
      refs[key] = value;
    }
  }
  return refs;
}

/** Initials for an avatar, e.g. "Alex Morgan" → "AM". */
export function initialsOf(name: string | undefined): string {
  if (!name) return '?';
  const parts = name
    .replace(/^(dr|mr|mrs|ms)\.?\s+/i, '')
    .split(/\s+/)
    .filter(Boolean);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase() || '?';
}
