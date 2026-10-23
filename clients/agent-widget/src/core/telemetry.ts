import type { TelemetryOptions } from '../types';

const hex = (bytes: number): string => {
  const buf = new Uint8Array(bytes);
  globalThis.crypto.getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('');
};

export const randomId = (prefix = ''): string => `${prefix}${hex(8)}`;

/**
 * Emits privacy-safe client telemetry and builds W3C traceparent headers so a turn can be
 * followed from the widget through the relay, APIM and agents (Azure Monitor / Datadog).
 * Never pass message text, card data or member fields to `track`.
 */
export class Telemetry {
  private readonly traceId: string;

  constructor(private readonly options: TelemetryOptions | undefined) {
    const parent = options?.traceParent?.match(/^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$/);
    this.traceId = parent ? parent[1] : hex(16);
  }

  /** A new child span id per outgoing activity, under the page's trace. */
  nextTraceParent(): string {
    return `00-${this.traceId}-${hex(8)}-01`;
  }

  track(name: string, properties: Record<string, unknown> = {}): void {
    try {
      this.options?.onEvent?.(name, { ...properties, sessionId: this.options?.sessionId, ts: Date.now() });
    } catch {
      // Telemetry must never break the widget.
    }
  }
}
