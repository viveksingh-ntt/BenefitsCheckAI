/**
 * Card renderer contract. The widget never depends on a specific Adaptive Cards
 * implementation: the built-in lite renderer is the default, and
 * `createSdkRenderer(AdaptiveCards)` adapts Microsoft's official SDK.
 */

export type CardActionType = 'Action.Submit' | 'Action.Execute' | 'Action.OpenUrl';

export interface CardActionInvocation {
  type: CardActionType;
  title?: string;
  verb?: string;
  url?: string;
  /** action.data merged with gathered inputs (Submit / Execute). */
  data: Record<string, unknown>;
  /** Raw action.data without inputs (used for flags such as keepActive). */
  actionData: Record<string, unknown>;
}

export interface CardRenderContext {
  /** Sanitized markdown → HTML. */
  markdown: (text: string) => string;
  onAction: (action: CardActionInvocation) => void;
  /** Unique prefix for element ids inside this card. */
  idPrefix: string;
  locale: string;
  strings: { required: string };
}

export interface RenderedCard {
  element: HTMLElement;
  /** Disable inputs and actions (card answered / stale). */
  setDisabled(disabled: boolean): void;
}

export interface CardRenderer {
  readonly name: string;
  /** Highest Adaptive Cards schema version supported. */
  readonly maxVersion: string;
  render(card: Record<string, unknown>, context: CardRenderContext): RenderedCard;
}

export const ADAPTIVE_CARD_CONTENT_TYPE = 'application/vnd.microsoft.card.adaptive';

export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}
