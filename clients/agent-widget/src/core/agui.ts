import { ADAPTIVE_CARD_CONTENT_TYPE } from '../cards/renderer';
import type { Activity, CardAction, DirectLineTokenResponse, TokenRequest } from '../types';
import { Emitter, type ConnectionStatus, type Transport } from './transport';

/**
 * AG-UI transport: the widget talks to the Agent relay's AG-UI host instead of Direct Line.
 *
 * - One `POST {endpoint}/run` per turn with a `RunAgentInput`; the reply is a Server-Sent Events stream of AG-UI events
 *   (https://docs.ag-ui.com/concepts/events), read with fetch so the chat token travels in a header.
 * - Events are mapped back onto the widget's activity model, so rendering, cards, chips and events need no changes.
 * - Human confirmation uses AG-UI interrupts: a run that ends with `outcome.type = "interrupt"` leaves the interrupt
 *   open; the card's Confirm/Submit button answers it with `resume` on the next run. Any other input cancels it.
 * - `{endpoint}/threads/{threadId}` restores the transcript and open interrupts after a page reload.
 *
 * The token comes from the portal backend exactly as for Direct Line (`getToken` / `tokenUrlFetcher`):
 * `{ token, conversationId (= threadId), userId, expires_in }`.
 */
export interface AgUiTransportOptions {
  getToken: (request: TokenRequest) => Promise<DirectLineTokenResponse>;
  /** Base URL of the relay's AG-UI host, e.g. `https://chat.healthgen.example/agui`. */
  endpoint: string;
  fetchImpl?: typeof fetch;
  setTimeoutImpl?: typeof setTimeout;
  clearTimeoutImpl?: typeof clearTimeout;
}

/** An AG-UI event as it arrives on the wire (`type` in upper snake case, fields camelCase). */
export interface AgUiEvent {
  type: string;
  [key: string]: unknown;
}

export interface AgUiInterrupt {
  id: string;
  reason?: string;
  message?: string;
  expiresAt?: string;
  responseSchema?: unknown;
  metadata?: Record<string, unknown>;
}

interface ResumeEntry {
  interruptId: string;
  status: 'resolved' | 'cancelled';
  payload?: Record<string, unknown>;
}

interface RunInput {
  threadId: string;
  runId: string;
  messages: Array<{ id: string; role: 'user'; content: string }>;
  tools: [];
  context: Array<{ description: string; value: string }>;
  state: Record<string, never>;
  forwardedProps: Record<string, unknown>;
  resume?: ResumeEntry[];
}

const CONFIRM_VERBS = new Set(['appointment.confirm', 'referral.submit']);
const BOT = { id: 'care-assistant', name: 'Care assistant', role: 'bot' as const };

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

let counter = 0;
const localId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(counter += 1)}`;

export class AgUiTransport implements Transport {
  private readonly endpoint: string;
  private readonly fetchImpl: typeof fetch;
  private readonly setTimer: typeof setTimeout;
  private readonly clearTimer: typeof clearTimeout;
  private readonly activities = new Emitter<[Activity]>();
  private readonly statuses = new Emitter<[ConnectionStatus, string | undefined]>();

  private token = '';
  private threadId: string | undefined;
  private userIdValue = '';
  private status: ConnectionStatus = 'idle';
  private ended = false;
  private refreshTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly aborters = new Set<AbortController>();
  private lastRun: Promise<void> = Promise.resolve();
  private context: Record<string, string> = {};
  private readonly openInterrupts = new Map<string, AgUiInterrupt>();

  // Per-run assembly: the newest bot message is held briefly so chips, result chip and breadcrumb attach to it.
  private pending: Activity | undefined;
  private textBuffers = new Map<string, { text: string; seq: number }>();
  private breadcrumb: string | undefined;

  constructor(private readonly options: AgUiTransportOptions) {
    this.endpoint = options.endpoint.replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.setTimer = options.setTimeoutImpl ?? globalThis.setTimeout.bind(globalThis);
    this.clearTimer = options.clearTimeoutImpl ?? globalThis.clearTimeout.bind(globalThis);
  }

  get conversationId(): string | undefined {
    return this.threadId;
  }

  get userId(): string {
    return this.userIdValue;
  }

  /** Interrupts the relay left open (review cards awaiting Confirm). */
  get pendingInterrupts(): AgUiInterrupt[] {
    return [...this.openInterrupts.values()];
  }

  onActivity(listener: (activity: Activity) => void): () => void {
    return this.activities.on(listener);
  }

  onStatus(listener: (status: ConnectionStatus, detail?: string) => void): () => void {
    return this.statuses.on(listener);
  }

  async connect({ userId, resumeConversationId }: { userId: string; resumeConversationId?: string }): Promise<void> {
    this.userIdValue = userId;
    this.setStatus('connecting');
    const res = await this.options.getToken({ reason: resumeConversationId ? 'resume' : 'start', conversationId: resumeConversationId });
    if (!res.token || !res.conversationId) throw new Error('Token endpoint returned no AG-UI thread');
    this.token = res.token;
    this.threadId = res.conversationId;
    if (res.userId) this.userIdValue = res.userId;
    this.scheduleRefresh(res.expires_in);
    if (resumeConversationId && resumeConversationId === this.threadId) {
      try {
        await this.restore();
      } catch {
        // A missing transcript is not fatal: the conversation continues, just without history.
      }
    }
    this.setStatus('online');
  }

  async post(activity: Activity): Promise<string> {
    if (this.ended) throw new Error('Conversation ended');
    const id = localId('agui');
    const input = this.toRunInput(activity);
    if (!input) return id; // nothing to send (e.g. page context, kept for the next run)
    // Turns stay ordered: a run starts only after the previous run's stream has ended.
    const previous = this.lastRun;
    let release!: () => void;
    this.lastRun = new Promise<void>((resolve) => (release = resolve));
    try {
      await previous;
      const { streaming } = await this.startRun(input);
      void streaming.catch((err) => console.error('[agent-widget] AG-UI stream failed', err)).finally(release);
    } catch (err) {
      release();
      throw err;
    }
    return id;
  }

  end(): void {
    this.ended = true;
    if (this.refreshTimer) this.clearTimer(this.refreshTimer);
    for (const a of this.aborters) a.abort();
    this.aborters.clear();
    this.setStatus('ended');
    this.activities.clear();
    this.statuses.clear();
  }

  // ------------------------------------------------------------------ input

  private toRunInput(activity: Activity): RunInput | undefined {
    const forwardedProps: Record<string, unknown> = {};
    const messages: RunInput['messages'] = [];
    let resume: ResumeEntry[] | undefined;
    const value = (activity.value ?? {}) as Record<string, unknown>;

    if (activity.type === 'event') {
      if (activity.name === 'context') {
        const page = (value.page ?? {}) as { route?: string };
        if (typeof page.route === 'string') this.context.page = page.route;
        if (typeof value.locale === 'string') this.context.locale = value.locale;
        return undefined;
      }
      if (activity.name === 'startJourney') {
        forwardedProps.journey = { id: value.journeyId, params: value.params ?? {} };
      } else if (activity.name === 'handoffRequest') {
        forwardedProps.action = { verb: 'handoff' };
      } else {
        return undefined; // other client events have no AG-UI meaning
      }
    } else if (activity.type === 'message') {
      const action = value.action as { verb?: string; data?: Record<string, unknown> } | undefined;
      if (action?.verb) {
        const data = action.data ?? {};
        const interruptId = typeof data.actionId === 'string' ? data.actionId : undefined;
        if (CONFIRM_VERBS.has(action.verb) && interruptId && this.openInterrupts.has(interruptId)) {
          const note = (data.officeNote ?? data.clinicalNote) as string | undefined;
          resume = [
            {
              interruptId,
              status: 'resolved',
              payload: {
                approved: true,
                ...(note ? { note } : {}),
                ...(action.verb === 'referral.submit' ? { attest: data.attest === true || data.attest === 'true' } : {}),
              },
            },
          ];
        } else {
          forwardedProps.action = { verb: action.verb, data };
        }
      } else if (activity.text) {
        messages.push({ id: localId('m'), role: 'user', content: activity.text });
        if (value.params) forwardedProps.params = value.params;
      } else if (activity.value !== undefined) {
        forwardedProps.action = { verb: 'submit', data: value };
      } else {
        return undefined;
      }
    } else {
      return undefined;
    }

    // Every open interrupt must be answered: anything that is not its Confirm cancels it.
    const answered = new Set((resume ?? []).map((r) => r.interruptId));
    const cancels = [...this.openInterrupts.keys()].filter((k) => !answered.has(k)).map((k) => ({ interruptId: k, status: 'cancelled' as const }));
    if (cancels.length || resume) resume = [...(resume ?? []), ...cancels];

    return {
      threadId: this.threadId!,
      runId: localId('run'),
      messages,
      tools: [],
      context: Object.entries(this.context).map(([description, v]) => ({ description, value: v })),
      state: {},
      forwardedProps,
      ...(resume ? { resume } : {}),
    };
  }

  // ------------------------------------------------------------------ runs

  /** Resolves once the run is accepted, with a promise for the rest of its event stream (wrapped: promises flatten). */
  private async startRun(input: RunInput, retried = false): Promise<{ streaming: Promise<void> }> {
    const aborter = new AbortController();
    this.aborters.add(aborter);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.endpoint}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Authorization: `Bearer ${this.token}` },
        body: JSON.stringify(input),
        signal: aborter.signal,
      });
    } catch (err) {
      this.aborters.delete(aborter);
      throw err;
    }
    if (response.status === 401 && !retried && (await this.refreshToken())) {
      this.aborters.delete(aborter);
      return this.startRun(input, true);
    }
    if (!response.ok || !response.body) {
      this.aborters.delete(aborter);
      if (response.status === 401 || response.status === 403) this.setStatus('expiredToken', `AG-UI ${response.status}`);
      throw new HttpError(response.status, `AG-UI run failed (${response.status})`);
    }
    // Accepted: post() can resolve now while the stream is read in the background.
    return { streaming: this.readStream(response.body).finally(() => this.aborters.delete(aborter)) };
  }

  private async readStream(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut: number;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const data = frame
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).replace(/^ /, ''))
            .join('\n');
          if (!data) continue;
          try {
            this.handleEvent(JSON.parse(data) as AgUiEvent);
          } catch (err) {
            console.error('[agent-widget] bad AG-UI event', err);
          }
        }
      }
    } catch (err) {
      if (!this.ended) this.flush();
      if (!this.ended && (err as Error)?.name !== 'AbortError') throw err;
    }
    this.flush();
  }

  // ------------------------------------------------------------------ events → activities

  /** Maps one AG-UI event onto the widget's activity model. Public for tests and custom hosts. */
  handleEvent(ev: AgUiEvent): void {
    switch (ev.type) {
      case 'STEP_STARTED':
        this.emit({ type: 'typing', from: BOT, text: String(ev.stepName ?? ''), entities: [{ type: 'streaminfo', streamType: 'informative', streamSequence: 1 }] });
        return;
      case 'TEXT_MESSAGE_START':
        this.flush();
        this.textBuffers.set(String(ev.messageId), { text: '', seq: 1 });
        return;
      case 'TEXT_MESSAGE_CONTENT': {
        const id = String(ev.messageId);
        const buf = this.textBuffers.get(id) ?? { text: '', seq: 1 };
        buf.text += String(ev.delta ?? '');
        buf.seq += 1;
        this.textBuffers.set(id, buf);
        this.emit({ type: 'typing', id: `${id}-s${buf.seq}`, from: BOT, text: buf.text, entities: [{ type: 'streaminfo', streamType: 'streaming', streamId: id, streamSequence: buf.seq }] });
        return;
      }
      case 'TEXT_MESSAGE_END': {
        const id = String(ev.messageId);
        const buf = this.textBuffers.get(id);
        this.textBuffers.delete(id);
        this.pending = {
          type: 'message',
          id,
          from: BOT,
          text: buf?.text ?? '',
          textFormat: 'markdown',
          entities: buf ? [{ type: 'streaminfo', streamType: 'final', streamId: id }] : [],
          channelData: this.breadcrumb ? { breadcrumb: this.breadcrumb } : {},
        };
        return;
      }
      case 'ACTIVITY_SNAPSHOT':
        this.applySnapshot(String(ev.messageId), String(ev.activityType), (ev.content ?? {}) as Record<string, unknown>);
        return;
      case 'STATE_SNAPSHOT': {
        const crumb = (ev.snapshot as Record<string, unknown> | undefined)?.breadcrumb;
        if (typeof crumb === 'string') this.setBreadcrumb(crumb);
        return;
      }
      case 'STATE_DELTA':
        for (const op of (ev.delta as Array<{ op: string; path: string; value?: unknown }>) ?? []) {
          if (op.path === '/breadcrumb' && typeof op.value === 'string') this.setBreadcrumb(op.value);
        }
        return;
      case 'CUSTOM':
        if (ev.name === 'navigate' || ev.name === 'handoff') this.emit({ type: 'event', from: BOT, name: String(ev.name), value: ev.value });
        return;
      case 'RUN_FINISHED': {
        this.flush();
        const outcome = ev.outcome as { type?: string; interrupts?: AgUiInterrupt[] } | undefined;
        // A finished run addressed every interrupt it was sent; only the ones it leaves open remain.
        this.openInterrupts.clear();
        if (outcome?.type === 'interrupt') for (const i of outcome.interrupts ?? []) this.openInterrupts.set(i.id, i);
        return;
      }
      case 'RUN_ERROR':
        this.flush();
        this.emit({ type: 'message', id: localId('err'), from: BOT, text: String(ev.message ?? 'Something went wrong.'), channelData: { resultChip: { text: 'Not completed', state: 'warning' } } });
        return;
      default:
        return; // RUN_STARTED, STEP_FINISHED, tool and reasoning events: nothing to draw
    }
  }

  private applySnapshot(messageId: string, kind: string, content: Record<string, unknown>): void {
    if (kind === 'adaptive_card') {
      this.flush();
      this.pending = {
        type: 'message',
        id: messageId,
        from: BOT,
        attachments: [{ contentType: ADAPTIVE_CARD_CONTENT_TYPE, content: content.card as Record<string, unknown> }],
        channelData: { templateId: content.templateId as string | undefined, ...(this.breadcrumb ? { breadcrumb: this.breadcrumb } : {}) },
      };
    } else if (kind === 'suggestions' && this.pending) {
      const actions = ((content.actions as Array<{ title: string; value?: string; recommended?: boolean }>) ?? []).map(
        (a): CardAction => ({ type: 'imBack', title: a.title, value: a.value ?? a.title, ...(a.recommended ? { channelData: { recommended: true } } : {}) }),
      );
      this.pending = { ...this.pending, suggestedActions: { actions } };
    } else if (kind === 'result_chip' && this.pending) {
      this.pending = {
        ...this.pending,
        channelData: { ...this.pending.channelData, resultChip: { text: String(content.text ?? ''), state: content.state === 'warning' ? 'warning' : 'done' } },
      };
    }
  }

  private setBreadcrumb(crumb: string): void {
    this.breadcrumb = crumb;
    if (this.pending) this.pending = { ...this.pending, channelData: { ...this.pending.channelData, breadcrumb: crumb } };
  }

  private flush(): void {
    if (!this.pending) return;
    const a = this.pending;
    this.pending = undefined;
    this.emit(a);
  }

  private emit(activity: Activity): void {
    if (this.ended) return;
    this.activities.emit({ conversation: this.threadId ? { id: this.threadId } : undefined, timestamp: new Date().toISOString(), ...activity });
  }

  // ------------------------------------------------------------------ reloads and tokens

  private async restore(): Promise<void> {
    const res = await this.fetchImpl(`${this.endpoint}/threads/${encodeURIComponent(this.threadId!)}`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (!res.ok) return;
    const snap = (await res.json()) as {
      messages?: Array<{ id: string; role: string; content?: unknown; activityType?: string }>;
      interrupts?: AgUiInterrupt[];
      state?: { breadcrumb?: string };
    };
    if (snap.state?.breadcrumb) this.breadcrumb = snap.state.breadcrumb;
    for (const m of snap.messages ?? []) {
      if (m.role === 'user' && typeof m.content === 'string') {
        this.flush();
        this.emit({ type: 'message', id: m.id, from: { id: this.userIdValue, role: 'user' }, text: m.content });
      } else if (m.role === 'assistant' && typeof m.content === 'string') {
        this.flush();
        this.pending = { type: 'message', id: m.id, from: BOT, text: m.content, textFormat: 'markdown', channelData: {} };
      } else if (m.role === 'activity' && m.activityType) {
        this.applySnapshot(m.id, m.activityType, (m.content ?? {}) as Record<string, unknown>);
      }
    }
    this.flush();
    for (const i of snap.interrupts ?? []) this.openInterrupts.set(i.id, i);
  }

  private scheduleRefresh(expiresIn?: number): void {
    if (this.refreshTimer) this.clearTimer(this.refreshTimer);
    if (!expiresIn) return;
    const ms = Math.max(30, expiresIn - 60) * 1000;
    this.refreshTimer = this.setTimer(() => {
      void this.refreshToken().then((ok) => {
        if (!ok) this.setStatus('expiredToken', 'Chat token could not be refreshed');
      });
    }, ms);
  }

  private async refreshToken(): Promise<boolean> {
    try {
      const res = await this.options.getToken({ reason: 'refresh', conversationId: this.threadId });
      if (!res.token || res.conversationId !== this.threadId) return false; // a new thread means the old session ended
      this.token = res.token;
      this.scheduleRefresh(res.expires_in);
      return true;
    } catch {
      return false;
    }
  }

  private setStatus(status: ConnectionStatus, detail?: string): void {
    if (this.status === status) return;
    this.status = status;
    this.statuses.emit(status, detail);
  }
}
