/**
 * Public types for the Agentic Client Widget host API and the Direct Line
 * activity shapes the widget understands.
 *
 * Contract summary (see README):
 *  - Host page → widget: HTML attributes, init(options), setContext(), startJourney(), sendMessage()
 *  - Widget → host page: DOM CustomEvents (ready, open, close, navigate, action, tokenExpired, handoff, error)
 *  - Widget ↔ Agent relay: Direct Line activities (message, typing, event)
 */

// ---------------------------------------------------------------------------
// Direct Line / Bot Framework activity subset
// ---------------------------------------------------------------------------

export interface ChannelAccount {
  id: string;
  name?: string;
  role?: 'user' | 'bot';
}

export interface Attachment {
  contentType: string;
  content?: unknown;
  contentUrl?: string;
  name?: string;
}

/** Bot Framework CardAction (used by suggestedActions). */
export interface CardAction {
  type: 'imBack' | 'postBack' | 'messageBack' | 'openUrl' | string;
  title: string;
  value?: unknown;
  text?: string;
  displayText?: string;
  image?: string;
  /** Widget extension: `{ recommended: true }` highlights the chip. */
  channelData?: { recommended?: boolean; [key: string]: unknown };
}

/** Streaming entity used by the M365 Agents SDK / Copilot Studio streaming protocol. */
export interface StreamInfoEntity {
  type: 'streaminfo';
  streamId?: string;
  streamType: 'informative' | 'streaming' | 'final';
  streamSequence?: number;
}

export type Entity = StreamInfoEntity | { type: string; [key: string]: unknown };

/**
 * channelData the widget reads from relay activities. All optional.
 * These are a widget ↔ relay convention, documented in README "Relay contract".
 */
export interface RelayChannelData {
  /** Collapsed tool-activity summary shown under the message, e.g. "Plan eligibility and benefits reviewed". */
  resultChip?: { text: string; state?: 'done' | 'warning' };
  /** Journey step shown in the breadcrumb strip, e.g. "Benefit check". */
  breadcrumb?: string;
  /** Card template id (for telemetry only). */
  templateId?: string;
  [key: string]: unknown;
}

export interface Activity {
  type: 'message' | 'typing' | 'event' | 'invoke' | 'conversationUpdate' | string;
  id?: string;
  timestamp?: string;
  localTimestamp?: string;
  from: ChannelAccount;
  conversation?: { id: string };
  text?: string;
  textFormat?: 'markdown' | 'plain' | 'xml';
  locale?: string;
  attachments?: Attachment[];
  attachmentLayout?: 'list' | 'carousel';
  suggestedActions?: { actions: CardAction[]; to?: string[] };
  name?: string;
  value?: unknown;
  entities?: Entity[];
  channelData?: RelayChannelData & Record<string, unknown>;
  replyToId?: string;
}

// ---------------------------------------------------------------------------
// Host API
// ---------------------------------------------------------------------------

export type PortalAudience = 'member' | 'provider';
export type WidgetMode = 'launcher' | 'docked' | 'inline' | 'fullpage';
export type WidgetPosition = 'bottom-right' | 'bottom-left' | 'right';
export type WidgetEnvironment = 'prod' | 'test' | 'demo';

/** Response from the portal backend's Direct Line token endpoint (Direct Line tokens/generate shape). */
export interface DirectLineTokenResponse {
  token: string;
  conversationId?: string;
  expires_in?: number;
  /** Optional: when the backend already started the conversation. */
  streamUrl?: string;
  /** Optional: the user id the token is bound to (Direct Line requires activities to use it). */
  userId?: string;
}

export interface TokenRequest {
  /** Present when resuming or refreshing an existing conversation. */
  conversationId?: string;
  reason: 'start' | 'refresh' | 'resume';
}

export interface MemberContext {
  /** Opaque reference resolved server-side. Never the full member ID. */
  ref: string;
  displayName: string;
  planName?: string;
  /** Last 4 characters of the member ID, for display only. */
  idLast4?: string;
  status?: string;
  relationship?: 'self' | 'dependent' | 'patient';
}

export interface ProviderContext {
  npi?: string;
  tin?: string;
  orgName?: string;
}

export interface PageContext {
  route?: string;
  /** e.g. "Benefit check" or "Member · Benefit check". */
  breadcrumb?: string;
  entity?: { type: string; ref: string };
}

export interface WidgetContext {
  member?: MemberContext;
  provider?: ProviderContext;
  page?: PageContext;
  /** Free-form, non-PHI hints for the agent. */
  hints?: Record<string, string | number | boolean>;
}

export interface WidgetFeatures {
  attachments?: boolean;
  feedback?: boolean;
  suggestions?: boolean;
  /** Resume the same conversation across page loads (sessionStorage, conversation id only). */
  history?: boolean;
  handoff?: boolean;
}

export interface WidgetLabels {
  title?: string;
  tagline?: string;
  placeholder?: string;
  disclaimer?: string;
  support?: string;
  launcher?: string;
}

export interface ThemeTokens {
  brand?: string;
  brandStrong?: string;
  brandSoft?: string;
  brandContrast?: string;
  surface?: string;
  surfaceAlt?: string;
  surfaceSunken?: string;
  border?: string;
  borderStrong?: string;
  text?: string;
  textMuted?: string;
  good?: string;
  warning?: string;
  attention?: string;
  radius?: string;
  fontFamily?: string;
}

export interface TelemetryOptions {
  sessionId?: string;
  /** W3C traceparent of the page; a child span id is generated per outgoing activity. */
  traceParent?: string;
  onEvent?: (name: string, properties: Record<string, unknown>) => void;
}

export interface WidgetOptions {
  apiVersion?: 1;
  /** Returns a Direct Line token from the portal backend. Required unless `tokenUrl` or `transport` is given. */
  getToken?: (request: TokenRequest) => Promise<DirectLineTokenResponse>;
  /** Alternative to getToken: the widget POSTs { conversationId?, reason } here with credentials: 'include'. */
  tokenUrl?: string;
  /** Direct Line base URL (regional / private endpoints). Default: https://directline.botframework.com/v3/directline */
  directLineDomain?: string;
  /** Use WebSocket streaming (default) or HTTP polling. */
  webSocket?: boolean;
  /**
   * Inject a custom transport (e.g. the mock relay). Pass a factory so newThread() and member
   * switches can open a fresh conversation; a single instance supports one conversation only.
   */
  transport?: import('./core/transport').Transport | (() => import('./core/transport').Transport);
  /** Inject a card renderer (default: built-in lite renderer). See createSdkRenderer for Microsoft's SDK. */
  cardRenderer?: import('./cards/renderer').CardRenderer;
  context?: WidgetContext;
  welcome?: { message?: string; suggestions?: string[] };
  features?: WidgetFeatures;
  /** Portal routes the agent may ask the host to open. Supports trailing `*`. */
  allowedRoutes?: string[];
  /** Origins Action.OpenUrl may open (default: same origin only). */
  allowedUrlOrigins?: string[];
  labels?: WidgetLabels;
  theme?: ThemeTokens;
  telemetry?: TelemetryOptions;
}

// ---------------------------------------------------------------------------
// Events dispatched on the <agent-widget> element
// ---------------------------------------------------------------------------

export interface NavigateEventDetail {
  route: string;
  params?: Record<string, unknown>;
}

export interface ActionEventDetail {
  /** Action.Execute verb, or `submit` for Action.Submit. */
  verb: string;
  /** Non-PHI references from the action data (keys ending in `Id`/`Ref`). */
  refs: Record<string, string>;
}

export interface HandoffEventDetail {
  reason: string;
  ticketRef?: string;
}

export interface WidgetErrorDetail {
  code: 'token' | 'connection' | 'send' | 'render' | 'config';
  message: string;
}

export interface WidgetEventMap {
  ready: CustomEvent<{ version: string }>;
  open: CustomEvent<void>;
  close: CustomEvent<void>;
  navigate: CustomEvent<NavigateEventDetail>;
  /** Cancelable: call preventDefault() to handle the action in the portal instead of sending it to the relay. */
  action: CustomEvent<ActionEventDetail>;
  tokenExpired: CustomEvent<void>;
  handoff: CustomEvent<HandoffEventDetail>;
  error: CustomEvent<WidgetErrorDetail>;
}
