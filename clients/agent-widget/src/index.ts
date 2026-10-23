/**
 * @yourorg/agent-widget — public entry.
 *
 * Importing this module registers the <agent-widget> custom element.
 */
import { AgentWidgetElement } from './ui/agent-widget';

export { AgentWidgetElement } from './ui/agent-widget';
export { DirectLineTransport, tokenUrlFetcher, DEFAULT_DIRECT_LINE_DOMAIN } from './core/directline';
export type { DirectLineTransportOptions } from './core/directline';
export { AgUiTransport } from './core/agui';
export type { AgUiTransportOptions, AgUiEvent, AgUiInterrupt } from './core/agui';
export type { Transport, ConnectionStatus } from './core/transport';
export { ConversationStore } from './core/conversation';
export { LiteCardRenderer } from './cards/lite/lite-renderer';
export { ADAPTIVE_CARD_CONTENT_TYPE } from './cards/renderer';
export type { CardRenderer, CardRenderContext, CardActionInvocation, RenderedCard } from './cards/renderer';
export { DEFAULT_THEME } from './ui/theme';
export { WIDGET_VERSION } from './version';
export * from './types';

export const TAG_NAME = 'agent-widget';

if (typeof customElements !== 'undefined' && !customElements.get(TAG_NAME)) {
  customElements.define(TAG_NAME, AgentWidgetElement);
}

declare global {
  interface HTMLElementTagNameMap {
    'agent-widget': AgentWidgetElement;
  }
}
