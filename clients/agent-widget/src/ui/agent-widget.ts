import type {
  Activity,
  CardAction,
  HandoffEventDetail,
  NavigateEventDetail,
  PortalAudience,
  WidgetContext,
  WidgetErrorDetail,
  WidgetMode,
  WidgetOptions,
} from '../types';
import { ConversationStore, type BotItem, type ChatItem, type ConversationState, type UserItem } from '../core/conversation';
import { DirectLineTransport, tokenUrlFetcher } from '../core/directline';
import type { ConnectionStatus, Transport } from '../core/transport';
import { stringsFor, type Strings } from '../core/i18n';
import { renderMarkdown } from '../core/markdown';
import { extractRefs, initialsOf, isRouteAllowed, isUrlAllowed } from '../core/policy';
import { Telemetry, randomId } from '../core/telemetry';
import { ADAPTIVE_CARD_CONTENT_TYPE, type CardActionInvocation, type CardRenderer, type RenderedCard } from '../cards/renderer';
import { LiteCardRenderer } from '../cards/lite/lite-renderer';
import { ICONS } from './icons';
import { WIDGET_CSS } from './styles';
import { resolveTheme, themeToCss } from './theme';
import { WIDGET_VERSION } from '../version';

type Attrs = Record<string, string | boolean | undefined>;

/** DOM helper. `html` is only ever given static icon markup or sanitized markdown. */
function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Array<Node | string | null | undefined | false>
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    if (key === 'class') node.className = String(value);
    else if (key === 'html') node.innerHTML = String(value);
    else if (key === 'text') node.textContent = String(value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}

interface LogEntry {
  node: HTMLElement;
  rev: number;
  textEl?: HTMLElement;
  chipEl?: HTMLElement;
  statusEl?: HTMLElement;
  feedbackEl?: HTMLElement;
  cardsRendered?: boolean;
}

interface PendingSend {
  activity: Activity;
  files: File[];
}

const OPENABLE_MODES: WidgetMode[] = ['launcher', 'docked'];
const SESSION_KEY = (agentId: string, memberRef: string | undefined) => `agent-widget:${agentId}:${memberRef ?? 'anon'}`;
/** Statuses after which the next action must open a new connection (resuming the conversation when possible). */
const NEEDS_RECONNECT: ConnectionStatus[] = ['failed', 'ended', 'expiredToken'];
/** Clear a progress indicator the relay never answered (dropped turn) after this long without updates. */
const PROGRESS_TIMEOUT_MS = 60_000;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const MAX_ATTACHMENTS = 5;

const errorText = (err: unknown): string => (err instanceof Error ? err.message : String(err));

/**
 * <agent-widget> — the embeddable Agentic Client Widget.
 *
 * Attributes: agent-id, portal (member|provider), mode (launcher|docked|inline|fullpage),
 * position, theme, locale, environment (prod|test|demo), open.
 * Methods: init, open, close, toggle, setContext, startJourney, sendMessage, newThread, destroy.
 * Events: ready, open, close, navigate, action (cancelable), tokenExpired, handoff, error.
 *
 * Public methods never reject: failures surface as `error` events and in the UI (failed message
 * with Retry, connection banner).
 */
export class AgentWidgetElement extends HTMLElement {
  static readonly observedAttributes = ['agent-id', 'portal', 'mode', 'position', 'theme', 'locale', 'environment', 'open'];
  static readonly version = WIDGET_VERSION;

  private readonly root: ShadowRoot;
  private options: WidgetOptions = {};
  private context: WidgetContext = {};
  private strings: Strings = stringsFor('en-US');
  private renderer: CardRenderer = new LiteCardRenderer();
  private telemetry = new Telemetry(undefined);
  private readonly userId = randomId('aw-user-');
  private store = new ConversationStore((a) => this.isSelf(a));
  private transport: Transport | undefined;
  private connecting: Promise<void> | undefined;
  /** Incremented whenever the transport is torn down; an in-flight connect from an older generation gives up. */
  private generation = 0;
  /** Conversation to resume on the next connect (after a dropped connection or expired token). */
  private resumeNext: string | undefined;
  private status: ConnectionStatus = 'idle';
  private initialized = false;
  private built = false;
  private wasOpen = false;
  private renderQueued = false;
  private progressKey = '';
  private progressTimer: ReturnType<typeof setTimeout> | undefined;
  private entries = new Map<string, LogEntry>();
  private pending = new Map<string, PendingSend>();
  private files: File[] = [];
  private unsubscribeStore: (() => void) | undefined;
  private transportSubs: Array<() => void> = [];

  // DOM refs
  private frame!: HTMLDivElement;
  private styleTheme!: HTMLStyleElement;
  private launcherBtn!: HTMLButtonElement;
  private panel!: HTMLElement;
  private titleEl!: HTMLElement;
  private taglineEl!: HTMLElement;
  private closeBtn!: HTMLButtonElement;
  private crumbText!: HTMLElement;
  private crumbEnv!: HTMLElement;
  private contextEl!: HTMLElement;
  private bannerEl!: HTMLElement;
  private logEl!: HTMLElement;
  private progressEl!: HTMLElement;
  private progressText!: HTMLElement;
  private suggestionsEl!: HTMLElement;
  private chipsEl!: HTMLElement;
  private suggestionsLabelText!: HTMLElement;
  private inputEl!: HTMLTextAreaElement;
  private sendBtn!: HTMLButtonElement;
  private attachBtn!: HTMLButtonElement;
  private fileInput!: HTMLInputElement;
  private filesEl!: HTMLElement;
  private disclaimerEl!: HTMLElement;
  private supportBtn!: HTMLButtonElement;
  private announcer!: HTMLElement;

  constructor() {
    super();
    this.root = this.attachShadow({ mode: 'open' });
  }

  // ================================================================ lifecycle

  connectedCallback(): void {
    if (!this.built) this.build();
    this.applyAttributes();
  }

  disconnectedCallback(): void {
    // Keep the conversation if the element is only moved; destroy() ends it explicitly.
  }

  attributeChangedCallback(): void {
    if (this.built) this.applyAttributes();
  }

  // ================================================================ host API

  /** Configure and start the widget. Call once, after the element is in the DOM. */
  init(options: WidgetOptions): this {
    if (!this.built) this.build();
    if (!options.transport && !options.getToken && !options.tokenUrl) {
      this.fail('config', 'init() needs getToken, tokenUrl or transport');
      return this;
    }
    this.options = { ...options, features: { suggestions: true, handoff: true, ...options.features } };
    this.context = { ...options.context };
    this.renderer = options.cardRenderer ?? this.renderer;
    this.telemetry = new Telemetry(options.telemetry);
    this.initialized = true;
    this.applyAttributes();
    this.telemetry.track('widget_init', { agentId: this.agentId, portal: this.portal, mode: this.mode, renderer: this.renderer.name });
    if (this.isOpen) this.connectQuietly();
    this.emit('ready', { version: WIDGET_VERSION });
    return this;
  }

  open(): void {
    if (this.isOpen) return;
    this.setAttribute('open', '');
  }

  close(): void {
    if (!this.isOpenable || !this.isOpen) return;
    this.removeAttribute('open');
  }

  toggle(): void {
    if (this.isOpen) this.close();
    else this.open();
  }

  /** Merge context. A different member.ref starts a new conversation so members never mix. */
  setContext(partial: WidgetContext): void {
    const previousRef = this.context.member?.ref;
    this.context = {
      ...this.context,
      ...partial,
      member: partial.member === undefined ? this.context.member : partial.member && { ...this.context.member, ...partial.member },
      provider: partial.provider === undefined ? this.context.provider : { ...this.context.provider, ...partial.provider },
      page: partial.page === undefined ? this.context.page : { ...this.context.page, ...partial.page },
    };
    this.renderContextHeader();
    this.renderCrumb();
    if (previousRef !== undefined && this.context.member?.ref !== previousRef) {
      this.clearResume(previousRef);
      this.newThread();
    } else if (this.transport && this.status === 'online') {
      void this.postEvent('context', this.contextPayload());
    }
  }

  /** Open into a journey with prefilled parameters, e.g. startJourney('doctor-search', { zip: '10012' }). */
  async startJourney(journeyId: string, params: Record<string, unknown> = {}): Promise<void> {
    this.open();
    const { prompt, ...rest } = params as { prompt?: unknown };
    this.telemetry.track('journey_start', { journeyId });
    if (typeof prompt === 'string' && prompt.trim()) {
      await this.sendMessage(prompt, { journeyId, ...rest });
      return;
    }
    this.store.setWorking();
    await this.postEvent('startJourney', { journeyId, params: rest }, true);
  }

  /** Send a message as the user. Optional params travel in activity.value.params (never shown). */
  async sendMessage(text: string, params?: Record<string, unknown>): Promise<void> {
    await this.postUserMessage(text, params ? { params } : undefined);
  }

  /** End the current conversation and start a fresh one. */
  newThread(): void {
    this.teardownTransport();
    this.resumeNext = undefined;
    this.clearResume(this.context.member?.ref);
    this.store.reset();
    this.entries.clear();
    this.logEl.replaceChildren();
    this.pending.clear();
    if (this.initialized && this.isOpen) this.connectQuietly();
  }

  /** Disconnect and remove listeners. The element can be removed afterwards. */
  destroy(): void {
    this.teardownTransport();
    this.unsubscribeStore?.();
    if (this.progressTimer) clearTimeout(this.progressTimer);
    this.initialized = false;
  }

  // ================================================================ attributes

  private get agentId(): string {
    return this.getAttribute('agent-id') ?? 'default';
  }

  private get portal(): PortalAudience {
    return this.getAttribute('portal') === 'provider' ? 'provider' : 'member';
  }

  private get mode(): WidgetMode {
    const mode = this.getAttribute('mode');
    return mode === 'docked' || mode === 'inline' || mode === 'fullpage' ? mode : 'launcher';
  }

  private get isOpenable(): boolean {
    return OPENABLE_MODES.includes(this.mode);
  }

  private get locale(): string {
    for (const candidate of [this.getAttribute('locale'), navigator.language]) {
      if (!candidate) continue;
      try {
        return Intl.getCanonicalLocales(candidate.replace(/@.*$/, '').replace('_', '-'))[0];
      } catch {
        // malformed tag (e.g. "en-US@posix"): try the next candidate
      }
    }
    return 'en-US';
  }

  private get isOpen(): boolean {
    return !this.isOpenable || this.hasAttribute('open');
  }

  private applyAttributes(): void {
    if (!this.built) return;
    this.strings = stringsFor(this.locale);
    const labels = this.options.labels ?? {};
    const position = this.getAttribute('position') === 'bottom-left' ? 'bottom-left' : 'bottom-right';
    const openable = this.isOpenable;
    this.frame.className = `aw-frame mode-${this.mode} pos-${position}`;
    this.styleTheme.textContent = themeToCss(resolveTheme(this.getAttribute('theme'), this.options.theme));

    const title = labels.title ?? this.strings.title;
    this.titleEl.textContent = title;
    this.taglineEl.textContent = labels.tagline ?? this.strings.tagline;
    // A floating panel is a non-modal dialog; an inline one is just a landmark region on the page.
    this.panel.setAttribute('role', openable ? 'dialog' : 'region');
    if (openable) this.panel.setAttribute('aria-modal', 'false');
    else this.panel.removeAttribute('aria-modal');
    this.panel.setAttribute('aria-label', title);
    this.launcherBtn.setAttribute('aria-label', labels.launcher ?? this.strings.launcher);
    this.closeBtn.setAttribute('aria-label', this.strings.close);
    this.closeBtn.hidden = !openable;
    const placeholder = labels.placeholder ?? this.strings.placeholder;
    this.inputEl.placeholder = placeholder;
    this.inputEl.setAttribute('aria-label', placeholder);
    this.sendBtn.setAttribute('aria-label', this.strings.send);
    this.attachBtn.setAttribute('aria-label', this.strings.attach);
    this.attachBtn.hidden = !this.options.features?.attachments;
    this.disclaimerEl.textContent = labels.disclaimer ?? this.strings.disclaimer;
    this.supportBtn.textContent = labels.support ?? this.strings.support;
    this.supportBtn.hidden = this.options.features?.handoff === false;
    this.suggestionsLabelText.textContent = this.strings.nextSteps;
    this.chipsEl.setAttribute('aria-label', this.strings.nextSteps);
    const environment = this.getAttribute('environment');
    this.crumbEnv.textContent = !environment || environment === 'prod' ? '' : this.strings.illustrative;

    const open = this.isOpen;
    this.panel.hidden = !open;
    this.launcherBtn.hidden = open || !openable;
    if (open !== this.wasOpen) {
      this.wasOpen = open;
      // Inline and full-page widgets are always open: no open/close events and no focus moves.
      if (openable && open) {
        this.emit('open', undefined);
        this.telemetry.track('widget_open', {});
        if (this.initialized) {
          this.connectQuietly();
          queueMicrotask(() => this.inputEl.focus({ preventScroll: true }));
        }
        this.scrollToEnd(true);
      } else if (openable) {
        this.emit('close', undefined);
        this.telemetry.track('widget_close', {});
        this.launcherBtn.focus({ preventScroll: true });
      }
    }
    this.renderCrumb();
    this.renderContextHeader();
  }

  // ================================================================ DOM build

  private build(): void {
    this.built = true;
    const style = h('style', { text: WIDGET_CSS });
    this.styleTheme = h('style');

    this.launcherBtn = h('button', { class: 'aw-launcher', type: 'button', html: ICONS.sparkle });
    this.launcherBtn.addEventListener('click', () => this.open());

    this.titleEl = h('h2', { class: 'aw-title' });
    this.taglineEl = h('div', { class: 'aw-tagline' });
    this.closeBtn = h('button', { class: 'aw-icon-btn', type: 'button', html: ICONS.close });
    this.closeBtn.addEventListener('click', () => this.close());
    const header = h(
      'header',
      { class: 'aw-header' },
      h('div', { class: 'aw-mark', html: ICONS.sparkle }),
      h('div', { class: 'aw-titles' }, this.titleEl, this.taglineEl),
      this.closeBtn,
    );

    this.crumbText = h('span', { class: 'aw-crumb-text' });
    this.crumbEnv = h('span', { class: 'aw-crumb-env' });
    const crumb = h('div', { class: 'aw-crumb' }, this.crumbText, this.crumbEnv);

    this.contextEl = h('div', { class: 'aw-context', hidden: true });
    this.bannerEl = h('div', { class: 'aw-banner', role: 'status', hidden: true });

    this.logEl = h('div', { class: 'aw-log-items', style: 'display:contents' });
    this.progressText = h('span');
    // The progress line is a status region of its own so it is announced once, not with the log.
    this.progressEl = h(
      'div',
      { class: 'aw-progress', role: 'status', hidden: true },
      h('span', { class: 'aw-dots', 'aria-hidden': 'true' }, h('span'), h('span'), h('span')),
      this.progressText,
    );
    const log = h('div', { class: 'aw-log', role: 'log', 'aria-live': 'polite', 'aria-relevant': 'additions', tabindex: '0' }, this.logEl, this.progressEl);

    this.suggestionsLabelText = h('span');
    const suggestionsLabel = h('div', { class: 'aw-suggestions-label' }, h('span', { html: ICONS.arrowRight, style: 'display:contents' }), this.suggestionsLabelText);
    this.chipsEl = h('div', { class: 'aw-chips', role: 'group' });
    this.suggestionsEl = h('div', { class: 'aw-suggestions', hidden: true }, suggestionsLabel, this.chipsEl);

    this.inputEl = h('textarea', { class: 'aw-input', rows: '1', maxlength: '2000' });
    this.inputEl.addEventListener('input', () => this.syncComposer());
    this.inputEl.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this.submitComposer();
      }
    });
    this.sendBtn = h('button', { class: 'aw-send', type: 'submit', html: ICONS.send, disabled: true });
    this.fileInput = h('input', { type: 'file', hidden: true, multiple: true });
    this.fileInput.addEventListener('change', () => this.addFiles(Array.from(this.fileInput.files ?? [])));
    this.attachBtn = h('button', { class: 'aw-icon-btn', type: 'button', html: ICONS.attach, hidden: true });
    this.attachBtn.addEventListener('click', () => this.fileInput.click());
    this.filesEl = h('div', { class: 'aw-files', hidden: true });
    const form = h(
      'form',
      { class: 'aw-composer' },
      this.filesEl,
      h('div', { class: 'aw-input-row' }, this.attachBtn, this.inputEl, this.sendBtn, this.fileInput),
    );
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.submitComposer();
    });

    this.disclaimerEl = h('span');
    this.supportBtn = h('button', { class: 'aw-support', type: 'button' });
    this.supportBtn.addEventListener('click', () => void this.requestHandoff());
    const footer = h('footer', { class: 'aw-footer' }, this.disclaimerEl, this.supportBtn);

    this.announcer = h('div', { class: 'sr-only', 'aria-live': 'assertive' });

    this.panel = h('section', { class: 'aw-panel' }, header, crumb, this.contextEl, log, this.bannerEl, this.suggestionsEl, form, footer, this.announcer);
    this.panel.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !event.defaultPrevented && this.isOpenable) {
        event.stopPropagation();
        this.close();
      }
    });

    this.frame = h('div', { class: 'aw-frame' }, this.launcherBtn, this.panel);
    this.root.append(style, this.styleTheme, this.frame);
    this.unsubscribeStore = this.store.subscribe(() => this.scheduleRender());
  }

  // ================================================================ connection

  private connectQuietly(): void {
    this.ensureConnected().catch(() => undefined); // failures are already shown in the banner and `error` event
  }

  /** Resolves once a live transport exists; rejects if the connection cannot be opened. */
  private async ensureConnected(): Promise<void> {
    if (!this.initialized) throw new Error('init() has not been called');
    // Loop because a newer connect (newThread, member switch) can supersede the one we awaited.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (!this.connecting || !this.transport || NEEDS_RECONNECT.includes(this.status)) {
        this.connecting = this.connect();
      }
      const current = this.connecting;
      await current;
      if (this.connecting === current && this.transport) return;
    }
    throw new Error('Connection was replaced repeatedly');
  }

  private async connect(): Promise<void> {
    const resumeConversationId = this.resumeNext ?? this.readResume();
    this.teardownTransport();
    const generation = this.generation;
    const opts = this.options;
    const transport: Transport =
      (typeof opts.transport === 'function' ? opts.transport() : opts.transport) ??
      new DirectLineTransport({
        getToken: opts.getToken ?? tokenUrlFetcher(opts.tokenUrl!),
        domain: opts.directLineDomain,
        webSocket: opts.webSocket,
      });
    this.transport = transport;
    this.transportSubs = [
      transport.onActivity((activity) => this.handleActivity(activity)),
      transport.onStatus((status, detail) => this.handleStatus(status, detail)),
    ];
    this.telemetry.track('connect_start', { resume: Boolean(resumeConversationId) });
    try {
      await transport.connect({ userId: this.userId, resumeConversationId });
    } catch (err) {
      if (generation !== this.generation) return; // superseded while connecting
      this.connecting = undefined;
      this.handleStatus('failed', errorText(err));
      throw err;
    }
    if (generation !== this.generation) return; // a newer conversation started meanwhile
    if (this.status === 'connecting' || this.status === 'idle') this.status = 'online';
    this.resumeNext = undefined;
    this.writeResume(transport.conversationId);
    this.telemetry.track('connect_ok', {});
    await this.postEvent('context', this.contextPayload());
    if (generation === this.generation && !this.store.snapshot.items.length && this.options.welcome?.message) {
      this.store.addLocalBot(
        this.options.welcome.message,
        (this.options.welcome.suggestions ?? []).map((title) => ({ type: 'imBack', title, value: title })),
      );
    }
  }

  private teardownTransport(): void {
    this.generation += 1;
    for (const unsubscribe of this.transportSubs) unsubscribe();
    this.transportSubs = [];
    this.transport?.end();
    this.transport = undefined;
    this.connecting = undefined;
    this.status = 'idle';
  }

  private handleStatus(status: ConnectionStatus, detail?: string): void {
    this.status = status;
    if (NEEDS_RECONNECT.includes(status) && this.transport?.conversationId) {
      this.resumeNext = this.transport.conversationId; // reconnect to the same conversation next time
    }
    if (status === 'online' || status === 'connecting') {
      this.showBanner(null);
    } else if (status === 'reconnecting') {
      this.showBanner(this.strings.reconnecting);
    } else if (status === 'expiredToken') {
      this.store.clearProgress();
      this.showBanner(this.strings.sessionExpired, true);
      this.emit('tokenExpired', undefined);
    } else if (status === 'failed') {
      this.store.clearProgress();
      this.showBanner(this.strings.offline, true, () => {
        this.showBanner(null);
        this.connectQuietly();
      });
      this.fail('connection', detail ?? 'Connection failed');
    }
  }

  private isSelf(activity: Activity): boolean {
    const id = activity.from?.id;
    return activity.from?.role === 'user' || id === this.userId || (id !== undefined && id === this.transport?.userId);
  }

  private handleActivity(activity: Activity): void {
    if (activity.type === 'event' && !this.isSelf(activity)) {
      this.handleRelayEvent(activity);
      return;
    }
    this.store.apply(activity);
  }

  private handleRelayEvent(activity: Activity): void {
    const value = (activity.value ?? {}) as Record<string, unknown>;
    switch (activity.name) {
      case 'navigate': {
        const detail: NavigateEventDetail = { route: String(value.route ?? ''), params: value.params as Record<string, unknown> | undefined };
        if (isRouteAllowed(detail.route, this.options.allowedRoutes)) {
          this.telemetry.track('navigate', { route: detail.route.split('?')[0] });
          this.emit('navigate', detail);
        } else {
          this.telemetry.track('navigate_blocked', {});
          console.warn('[agent-widget] navigation blocked by allowedRoutes:', detail.route);
        }
        break;
      }
      case 'handoff': {
        const detail: HandoffEventDetail = { reason: String(value.reason ?? 'agent'), ticketRef: typeof value.ticketRef === 'string' ? value.ticketRef : undefined };
        this.emit('handoff', detail);
        break;
      }
      default:
        break;
    }
  }

  private contextPayload(): Record<string, unknown> {
    // Only references and page state go to the relay; display fields stay in the browser.
    const { member, provider, page, hints } = this.context;
    return {
      agentId: this.agentId,
      portal: this.portal,
      locale: this.locale,
      member: member ? { ref: member.ref, relationship: member.relationship } : undefined,
      provider: provider ? { npi: provider.npi, tin: provider.tin } : undefined,
      page,
      hints,
    };
  }

  private channelData(clientActivityId?: string): Record<string, unknown> {
    return {
      clientActivityId,
      traceparent: this.telemetry.nextTraceParent(),
      widget: { version: WIDGET_VERSION, portal: this.portal, agentId: this.agentId },
    };
  }

  /** Posts an event activity. Returns false (and reports the error) when it could not be sent. */
  private async postEvent(name: string, value: unknown, connectFirst = false): Promise<boolean> {
    try {
      if (connectFirst) await this.ensureConnected();
      if (!this.transport) return false;
      await this.transport.post({ type: 'event', name, value, from: { id: this.userId, role: 'user' }, channelData: this.channelData() });
      return true;
    } catch (err) {
      if (connectFirst) this.store.clearProgress();
      this.fail('send', errorText(err));
      return false;
    }
  }

  /** Posts a message with no visible bubble (card actions, postBack chips). Returns false on failure. */
  private async postSilent(value: unknown, extra: Partial<Activity> = {}): Promise<boolean> {
    this.store.setWorking();
    try {
      await this.ensureConnected();
      await this.transport!.post({
        type: 'message',
        from: { id: this.userId, role: 'user' },
        value,
        locale: this.locale,
        ...extra,
        channelData: { ...this.channelData(randomId('c-')), ...extra.channelData },
      });
      return true;
    } catch (err) {
      this.store.clearProgress();
      this.fail('send', errorText(err));
      return false;
    }
  }

  /** Shows the user's bubble immediately, then delivers it. Text is never lost: failures show Retry. */
  private async postUserMessage(text: string, value?: unknown): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed && !this.files.length) return;
    this.open();
    const clientId = randomId('c-');
    const files = this.files;
    this.files = [];
    this.renderFiles();
    this.store.addLocalUser(clientId, trimmed || undefined, files.map((f) => f.name));
    const activity: Activity = {
      type: 'message',
      from: { id: this.userId, role: 'user' },
      text: trimmed || undefined,
      textFormat: 'plain',
      locale: this.locale,
      value,
      channelData: this.channelData(clientId),
    };
    this.pending.set(clientId, { activity, files });
    this.telemetry.track('message_sent', { hasValue: value !== undefined, files: files.length });
    await this.deliver(clientId);
  }

  private async deliver(clientId: string): Promise<void> {
    const pending = this.pending.get(clientId);
    if (!pending) return;
    this.store.markSending(clientId);
    try {
      await this.ensureConnected();
      const transport = this.transport;
      if (!transport) throw new Error('Not connected');
      let id: string;
      if (pending.files.length) {
        if (!transport.upload) throw new Error('This assistant does not accept attachments');
        id = '';
        for (const [i, file] of pending.files.entries()) {
          id = await transport.upload(file, i === 0 ? pending.activity : { ...pending.activity, text: undefined });
        }
      } else {
        id = await transport.post(pending.activity);
      }
      this.pending.delete(clientId);
      this.store.markSent(clientId, id);
      this.store.setWorking();
    } catch (err) {
      this.store.markFailed(clientId);
      this.fail('send', errorText(err));
    }
  }

  // ================================================================ actions

  private submitComposer(): void {
    const text = this.inputEl.value;
    if (!text.trim() && !this.files.length) return;
    this.inputEl.value = '';
    this.syncComposer();
    void this.sendMessage(text);
  }

  private syncComposer(): void {
    this.inputEl.style.height = 'auto';
    this.inputEl.style.height = `${Math.min(this.inputEl.scrollHeight, 120)}px`;
    this.sendBtn.disabled = !this.inputEl.value.trim() && !this.files.length;
  }

  private addFiles(added: File[]): void {
    this.fileInput.value = '';
    const tooLarge = added.filter((file) => file.size > MAX_ATTACHMENT_BYTES);
    const accepted = added.filter((file) => file.size <= MAX_ATTACHMENT_BYTES);
    this.files = [...this.files, ...accepted].slice(0, MAX_ATTACHMENTS);
    if (tooLarge.length) this.announce(this.strings.fileTooLarge, true);
    this.renderFiles();
  }

  private async onSuggestion(action: CardAction): Promise<void> {
    this.telemetry.track('suggestion_click', { type: action.type });
    switch (action.type) {
      case 'openUrl':
        this.openUrl(String(action.value ?? ''));
        return;
      case 'postBack':
        await this.postSilent(action.value);
        return;
      case 'messageBack':
        await this.postUserMessage(action.displayText ?? action.text ?? action.title, action.value);
        return;
      default:
        await this.postUserMessage(String(action.value ?? action.title));
    }
  }

  private async onCardAction(item: BotItem, card: RenderedCard, wrapper: HTMLElement, invocation: CardActionInvocation): Promise<void> {
    if (invocation.type === 'Action.OpenUrl') {
      this.openUrl(invocation.url ?? '');
      return;
    }
    const verb = invocation.verb ?? 'submit';
    const allowed = this.emit('action', { verb, refs: extractRefs(invocation.data) }, true);
    this.telemetry.track('card_action', { verb, handledByHost: !allowed });
    if (!allowed) return;

    const keepActive = invocation.actionData.keepActive === true;
    if (!keepActive) this.markStale(wrapper, card, invocation.title);
    const { keepActive: _ignored, ...data } = invocation.data;
    const value = invocation.type === 'Action.Execute' ? { action: { type: 'Action.Execute', verb, data } } : data;
    const sent = await this.postSilent(value, { replyToId: item.activityId, channelData: { actionType: invocation.type } });
    if (!sent && !keepActive) this.unmarkStale(wrapper, card);
  }

  private markStale(wrapper: HTMLElement, card: RenderedCard, title?: string): void {
    card.setDisabled(true);
    wrapper.classList.add('is-stale');
    wrapper.querySelector('.aw-card-status')?.remove();
    wrapper.append(h('div', { class: 'aw-card-status' }, h('span', { html: ICONS.checkCircle, style: 'display:contents' }), title ?? this.strings.cardSubmitted));
  }

  private unmarkStale(wrapper: HTMLElement, card: RenderedCard): void {
    card.setDisabled(false);
    wrapper.classList.remove('is-stale');
    wrapper.querySelector('.aw-card-status')?.remove();
  }

  private openUrl(url: string): void {
    if (isUrlAllowed(url, this.options.allowedUrlOrigins, location.origin)) {
      window.open(url, '_blank', 'noopener,noreferrer');
    } else {
      this.telemetry.track('open_url_blocked', {});
      console.warn('[agent-widget] URL blocked by allowedUrlOrigins:', url);
    }
  }

  private async requestHandoff(): Promise<void> {
    this.telemetry.track('handoff_request', {});
    this.open();
    this.store.setWorking();
    await this.postEvent('handoffRequest', { reason: 'user_request' }, true);
  }

  private async sendFeedback(item: BotItem, rating: 'up' | 'down'): Promise<void> {
    this.store.setFeedback(item.id, rating);
    this.announce(this.strings.thanks);
    this.telemetry.track('feedback', { rating });
    await this.postEvent('feedback', { replyToId: item.activityId, rating });
  }

  // ================================================================ rendering

  private scheduleRender(): void {
    if (this.renderQueued) return;
    this.renderQueued = true;
    requestAnimationFrame(() => {
      this.renderQueued = false;
      this.render(this.store.snapshot);
    });
  }

  private render(state: ConversationState): void {
    const log = this.logEl.parentElement as HTMLElement;
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
    const seen = new Set<string>();
    const desired: HTMLElement[] = [];
    let lastTime = 0;

    for (const item of state.items) {
      if (!lastTime || item.timestamp - lastTime > 60 * 60 * 1000) {
        const key = `day-${item.id}`;
        let entry = this.entries.get(key);
        if (!entry) {
          entry = { node: h('div', { class: 'aw-day', text: this.formatTime(item.timestamp) }), rev: 0 };
          this.entries.set(key, entry);
        }
        seen.add(key);
        desired.push(entry.node);
      }
      lastTime = item.timestamp;
      seen.add(item.id);
      desired.push(this.renderItem(item));
    }

    for (const [key, entry] of this.entries) {
      if (!seen.has(key)) {
        entry.node.remove();
        this.entries.delete(key);
      }
    }
    desired.forEach((node, index) => {
      if (this.logEl.children[index] !== node) this.logEl.insertBefore(node, this.logEl.children[index] ?? null);
    });

    this.renderProgress(state.progress);
    this.renderSuggestions(state.suggestions);
    this.renderCrumb();
    this.scrollToEnd(nearBottom);
  }

  /** Updates the progress line only when it changes, and clears it if the relay goes silent. */
  private renderProgress(progress: ConversationState['progress']): void {
    const key = progress.active ? `on:${progress.text ?? ''}` : 'off';
    if (key === this.progressKey) return;
    this.progressKey = key;
    this.progressEl.hidden = !progress.active;
    this.progressText.textContent = progress.active ? (progress.text ?? this.strings.working) : '';
    if (this.progressTimer) clearTimeout(this.progressTimer);
    this.progressTimer = progress.active ? setTimeout(() => this.store.clearProgress(), PROGRESS_TIMEOUT_MS) : undefined;
  }

  private renderItem(item: ChatItem): HTMLElement {
    const existing = this.entries.get(item.id);
    if (existing && existing.rev === item.rev) return existing.node;
    if (existing) {
      if (item.kind === 'user') this.updateUser(existing, item);
      else this.updateBot(existing, item);
      existing.rev = item.rev;
      return existing.node;
    }
    const entry: LogEntry =
      item.kind === 'user'
        ? { node: h('div', { class: 'aw-user' }), rev: item.rev }
        : { node: h('div', { class: 'aw-bot' }), rev: item.rev };
    if (item.kind === 'user') this.updateUser(entry, item);
    else this.updateBot(entry, item);
    this.entries.set(item.id, entry);
    return entry.node;
  }

  /** Builds the bubble once and only swaps the status line, so screen readers don't re-read it. */
  private updateUser(entry: LogEntry, item: UserItem): void {
    if (!entry.textEl) {
      entry.textEl = h('div', { class: 'aw-bubble' });
      entry.textEl.textContent = item.text ?? '';
      if (item.attachmentNames?.length) entry.textEl.append(h('div', { class: 'aw-user-status', text: `📎 ${item.attachmentNames.join(', ')}` }));
      entry.node.append(entry.textEl);
    }
    entry.statusEl?.remove();
    entry.statusEl = undefined;
    if (item.status === 'failed') {
      const retry = h('button', { type: 'button', text: this.strings.retry });
      retry.addEventListener('click', () => void this.deliver(item.clientId ?? item.id));
      entry.statusEl = h('div', { class: 'aw-user-status is-failed', role: 'alert' }, `${this.strings.failed} `, retry);
    } else if (item.status === 'sending') {
      entry.statusEl = h('div', { class: 'aw-user-status', text: this.strings.sending });
    }
    if (entry.statusEl) entry.node.append(entry.statusEl);
  }

  private updateBot(entry: LogEntry, item: BotItem): void {
    // text
    if (item.text) {
      if (!entry.textEl) {
        entry.textEl = h('div', { class: 'aw-bot-text' });
        entry.node.prepend(entry.textEl);
      }
      if (item.textFormat === 'plain') entry.textEl.textContent = item.text;
      else entry.textEl.innerHTML = renderMarkdown(item.text);
      entry.textEl.classList.toggle('is-streaming', item.streaming);
      entry.textEl.setAttribute('aria-busy', String(item.streaming));
    }
    // result chip (after text, before cards)
    if (item.resultChip && !entry.chipEl) {
      entry.chipEl = h(
        'div',
        { class: `aw-chip-result${item.resultChip.state === 'warning' ? ' is-warning' : ''}` },
        h('span', { html: ICONS.checkCircle, style: 'display:contents' }),
        h('span', { text: item.resultChip.text }),
      );
      if (entry.textEl) entry.textEl.after(entry.chipEl);
      else entry.node.prepend(entry.chipEl);
    }
    // cards: rendered once, so inputs keep their state across updates
    if (!entry.cardsRendered && item.attachments.length) {
      entry.cardsRendered = true;
      item.attachments.forEach((attachment, index) => {
        if (attachment.contentType !== ADAPTIVE_CARD_CONTENT_TYPE || !attachment.content || typeof attachment.content !== 'object') return;
        entry.node.insertBefore(this.renderCard(item, attachment.content as Record<string, unknown>, index), entry.feedbackEl ?? null);
      });
    }
    // feedback (only on real relay messages)
    if (this.options.features?.feedback && !item.streaming && item.text && item.activityId) {
      if (!entry.feedbackEl) {
        entry.feedbackEl = h('div', { class: 'aw-feedback' });
        entry.node.append(entry.feedbackEl);
      }
      const up = h('button', { class: 'aw-icon-btn', type: 'button', html: ICONS.thumbUp, 'aria-label': this.strings.helpful, 'aria-pressed': String(item.feedback === 'up') });
      const down = h('button', { class: 'aw-icon-btn', type: 'button', html: ICONS.thumbDown, 'aria-label': this.strings.notHelpful, 'aria-pressed': String(item.feedback === 'down') });
      up.addEventListener('click', () => void this.sendFeedback(item, 'up'));
      down.addEventListener('click', () => void this.sendFeedback(item, 'down'));
      entry.feedbackEl.replaceChildren(up, down);
    }
  }

  private renderCard(item: BotItem, content: Record<string, unknown>, index: number): HTMLElement {
    const wrapper = h('article', { class: 'aw-card' });
    const heading = this.findCardTitle(content);
    if (heading) wrapper.setAttribute('aria-label', heading);
    try {
      let rendered: RenderedCard | undefined;
      rendered = this.renderer.render(content, {
        markdown: (text) => renderMarkdown(text),
        onAction: (invocation) => {
          if (rendered) void this.onCardAction(item, rendered, wrapper, invocation);
        },
        idPrefix: `aw-${item.id.replace(/[^A-Za-z0-9]/g, '').slice(-10)}-${index}`,
        locale: this.locale,
        strings: { required: this.strings.required },
      });
      wrapper.append(rendered.element);
      this.telemetry.track('card_rendered', { templateId: item.templateId, renderer: this.renderer.name });
    } catch (err) {
      const fallback = (content as { fallbackText?: unknown }).fallbackText;
      wrapper.append(h('div', { class: 'ac-text', text: typeof fallback === 'string' ? fallback : 'This card could not be displayed.' }));
      this.fail('render', errorText(err));
    }
    return wrapper;
  }

  private findCardTitle(card: Record<string, unknown>): string | undefined {
    const body = Array.isArray(card.body) ? (card.body as Array<Record<string, unknown>>) : [];
    const heading = body.find((b) => b && b.type === 'TextBlock' && (b.style === 'heading' || b.weight === 'Bolder'));
    return typeof heading?.text === 'string' ? heading.text : undefined;
  }

  private renderSuggestions(actions: CardAction[]): void {
    const show = this.options.features?.suggestions !== false && actions.length > 0;
    this.suggestionsEl.hidden = !show;
    if (!show) {
      this.chipsEl.replaceChildren();
      return;
    }
    this.chipsEl.replaceChildren(
      ...actions.map((action) => {
        const chip = h('button', { class: `aw-chip${action.channelData?.recommended ? ' is-recommended' : ''}`, type: 'button', text: action.title });
        chip.addEventListener('click', () => void this.onSuggestion(action));
        return chip;
      }),
    );
  }

  private renderContextHeader(): void {
    if (!this.built) return;
    const member = this.context.member;
    this.contextEl.hidden = !member;
    if (!member) return;
    const label =
      this.portal === 'provider'
        ? `${this.strings.selectedMember}: ${member.displayName}`
        : `${member.displayName} · ${this.strings.yourPlan}`;
    const meta = [member.planName, member.idLast4 ? `${this.strings.idEnding} ${member.idLast4}` : undefined, member.status]
      .filter(Boolean)
      .join(' · ');
    this.contextEl.replaceChildren(
      h('div', { class: 'aw-avatar', 'aria-hidden': 'true', text: initialsOf(member.displayName) }),
      h('div', {}, h('div', { class: 'aw-context-name', text: label }), meta ? h('div', { class: 'aw-context-meta', text: meta }) : null),
    );
  }

  private renderCrumb(): void {
    if (!this.built) return;
    const portalLabel = this.portal === 'provider' ? this.strings.provider : this.strings.member;
    const crumb = this.store.snapshot.breadcrumb ?? this.context.page?.breadcrumb;
    this.crumbText.textContent = crumb ? (crumb.includes('·') ? crumb : `${portalLabel} · ${crumb}`) : portalLabel;
  }

  private renderFiles(): void {
    this.filesEl.hidden = !this.files.length;
    this.filesEl.replaceChildren(
      ...this.files.map((file, index) => {
        const remove = h('button', { type: 'button', 'aria-label': `${this.strings.remove} ${file.name}`, text: '×' });
        remove.addEventListener('click', () => {
          this.files.splice(index, 1);
          this.renderFiles();
        });
        return h('span', { class: 'aw-file' }, file.name, remove);
      }),
    );
    this.syncComposer();
  }

  private showBanner(message: string | null, isError = false, onRetry?: () => void): void {
    this.bannerEl.hidden = !message;
    if (!message) return;
    this.bannerEl.className = `aw-banner${isError ? ' is-error' : ''}`;
    const children: Node[] = [h('span', { text: message })];
    if (onRetry) {
      const retry = h('button', { type: 'button', text: this.strings.retry });
      retry.addEventListener('click', onRetry);
      children.push(retry);
    }
    this.bannerEl.replaceChildren(...children);
  }

  private scrollToEnd(force: boolean): void {
    if (!force) return;
    const log = this.logEl.parentElement as HTMLElement;
    requestAnimationFrame(() => {
      log.scrollTop = log.scrollHeight;
    });
  }

  private formatTime(ts: number): string {
    const date = new Date(ts);
    const time = new Intl.DateTimeFormat(this.locale, { hour: 'numeric', minute: '2-digit' }).format(date);
    const today = new Date().toDateString() === date.toDateString();
    const day = today ? this.strings.today : new Intl.DateTimeFormat(this.locale, { month: 'short', day: 'numeric' }).format(date);
    return `${day}, ${time}`;
  }

  private announce(text: string, visible = false): void {
    if (visible) {
      this.showBanner(text, true);
      setTimeout(() => {
        if (this.bannerEl.textContent === text) this.showBanner(null);
      }, 6000);
    }
    this.announcer.textContent = '';
    setTimeout(() => {
      this.announcer.textContent = text;
    }, 50);
  }

  // ================================================================ misc

  private readResume(): string | undefined {
    if (!this.options.features?.history) return undefined;
    try {
      return sessionStorage.getItem(SESSION_KEY(this.agentId, this.context.member?.ref)) ?? undefined;
    } catch {
      return undefined;
    }
  }

  private writeResume(conversationId: string | undefined): void {
    if (!this.options.features?.history || !conversationId) return;
    try {
      sessionStorage.setItem(SESSION_KEY(this.agentId, this.context.member?.ref), conversationId);
    } catch {
      /* storage unavailable */
    }
  }

  private clearResume(memberRef: string | undefined): void {
    try {
      sessionStorage.removeItem(SESSION_KEY(this.agentId, memberRef));
    } catch {
      /* storage unavailable */
    }
  }

  private fail(code: WidgetErrorDetail['code'], message: string): void {
    this.telemetry.track('error', { code });
    this.emit('error', { code, message });
  }

  /** Dispatches a DOM event on the host element. Returns false if a cancelable event was prevented. */
  private emit<T>(name: string, detail: T, cancelable = false): boolean {
    return this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true, cancelable }));
  }
}
