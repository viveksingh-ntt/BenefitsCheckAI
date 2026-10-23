import type { Activity, DirectLineTokenResponse, TokenRequest } from '../types';
import { Emitter, type ConnectionStatus, type Transport } from './transport';

export const DEFAULT_DIRECT_LINE_DOMAIN = 'https://directline.botframework.com/v3/directline';

export interface DirectLineTransportOptions {
  getToken: (request: TokenRequest) => Promise<DirectLineTokenResponse>;
  domain?: string;
  webSocket?: boolean;
  /** Polling interval when webSocket is false (ms). */
  pollingInterval?: number;
  /** Injection points for tests. */
  fetchImpl?: typeof fetch;
  WebSocketImpl?: typeof WebSocket;
  setTimeoutImpl?: typeof setTimeout;
  clearTimeoutImpl?: typeof clearTimeout;
  /** Max reconnect attempts before giving up. */
  maxReconnectAttempts?: number;
  /** How long to wait for the WebSocket to open before falling back to polling (ms). Default 10000. */
  socketOpenTimeout?: number;
}

interface ConversationResponse {
  conversationId: string;
  token?: string;
  expires_in?: number;
  streamUrl?: string;
}

interface ActivitySet {
  activities: Activity[];
  watermark?: string;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * Minimal, dependency-free Direct Line 3.0 client.
 *
 * - Token comes from the portal backend via `getToken` (never a Direct Line secret in the browser).
 * - WebSocket streaming with automatic reconnect (fresh streamUrl, resumes from watermark).
 * - Token refresh before expiry by calling `getToken({ reason: 'refresh', conversationId })`.
 * - HTTP polling fallback when WebSockets are blocked.
 */
export class DirectLineTransport implements Transport {
  private readonly domain: string;
  private readonly fetchImpl: typeof fetch;
  private readonly WebSocketImpl: typeof WebSocket | undefined;
  private readonly setTimer: typeof setTimeout;
  private readonly clearTimer: typeof clearTimeout;
  private readonly activities = new Emitter<[Activity]>();
  private readonly statuses = new Emitter<[ConnectionStatus, string | undefined]>();

  private token = '';
  private convId: string | undefined;
  private watermark: string | undefined;
  private socket: WebSocket | undefined;
  private refreshTimer: ReturnType<typeof setTimeout> | undefined;
  private pollTimer: ReturnType<typeof setTimeout> | undefined;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private reconnectAttempts = 0;
  private pollFailures = 0;
  private refreshing: Promise<void> | undefined;
  private ended = false;
  private userIdValue = '';
  private status: ConnectionStatus = 'idle';

  constructor(private readonly options: DirectLineTransportOptions) {
    this.domain = (options.domain ?? DEFAULT_DIRECT_LINE_DOMAIN).replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.WebSocketImpl = options.WebSocketImpl ?? globalThis.WebSocket;
    this.setTimer = options.setTimeoutImpl ?? globalThis.setTimeout.bind(globalThis);
    this.clearTimer = options.clearTimeoutImpl ?? globalThis.clearTimeout.bind(globalThis);
  }

  get conversationId(): string | undefined {
    return this.convId;
  }

  get userId(): string {
    return this.userIdValue;
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
    const tokenResponse = await this.options.getToken({
      reason: resumeConversationId ? 'resume' : 'start',
      conversationId: resumeConversationId,
    });
    this.token = tokenResponse.token;
    if (tokenResponse.userId) this.userIdValue = tokenResponse.userId;

    let conversation: ConversationResponse;
    const resumeId = resumeConversationId ?? tokenResponse.conversationId;
    if (resumeConversationId) {
      try {
        conversation = await this.request<ConversationResponse>('GET', `/conversations/${encodeURIComponent(resumeConversationId)}`);
      } catch {
        // Conversation expired or token not bound to it: start fresh.
        conversation = await this.request<ConversationResponse>('POST', '/conversations');
      }
    } else if (tokenResponse.streamUrl && resumeId) {
      conversation = { conversationId: resumeId, streamUrl: tokenResponse.streamUrl, expires_in: tokenResponse.expires_in };
    } else {
      conversation = await this.request<ConversationResponse>('POST', '/conversations');
    }

    this.convId = conversation.conversationId;
    if (conversation.token) this.token = conversation.token;
    this.scheduleRefresh(conversation.expires_in ?? tokenResponse.expires_in);

    if (this.options.webSocket !== false && this.WebSocketImpl && conversation.streamUrl) {
      // Wait for the stream so replies to the first post are not missed. Corporate proxies often
      // block WebSockets: fall back to HTTP polling instead of failing.
      const opened = await this.openSocket(conversation.streamUrl, this.options.socketOpenTimeout ?? 10_000);
      if (opened || this.ended) return;
      this.closeSocket();
    }
    this.setStatus('online');
    this.poll();
  }

  async post(activity: Activity): Promise<string> {
    if (!this.convId) throw new Error('Not connected');
    const body = { ...activity, from: { ...activity.from, id: this.userIdValue || activity.from.id } };
    const path = `/conversations/${encodeURIComponent(this.convId)}/activities`;
    try {
      const res = await this.request<{ id: string }>('POST', path, body);
      return res.id;
    } catch (err) {
      if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
        await this.refreshToken();
        const res = await this.request<{ id: string }>('POST', path, body);
        return res.id;
      }
      throw err;
    }
  }

  async upload(file: File, activity: Activity): Promise<string> {
    if (!this.convId) throw new Error('Not connected');
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('activity', new Blob([JSON.stringify(activity)], { type: 'application/vnd.microsoft.activity' }));
    const url = `${this.domain}/conversations/${encodeURIComponent(this.convId)}/upload?userId=${encodeURIComponent(this.userIdValue)}`;
    const res = await this.fetchImpl(url, { method: 'POST', headers: { Authorization: `Bearer ${this.token}` }, body: form });
    if (!res.ok) throw new HttpError(res.status, `Upload failed (${res.status})`);
    const json = (await res.json()) as { id: string };
    return json.id;
  }

  end(): void {
    this.ended = true;
    this.clearAllTimers();
    this.closeSocket();
    this.setStatus('ended');
    this.activities.clear();
    this.statuses.clear();
  }

  // -------------------------------------------------------------------------

  private setStatus(status: ConnectionStatus, detail?: string): void {
    if (this.status === status && !detail) return;
    this.status = status;
    this.statuses.emit(status, detail);
  }

  private async request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    const res = await this.fetchImpl(`${this.domain}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new HttpError(res.status, `Direct Line ${method} ${path} failed (${res.status})`);
    const text = await res.text();
    return (text ? JSON.parse(text) : {}) as T;
  }

  private closeSocket(): void {
    if (!this.socket) return;
    this.socket.onopen = null;
    this.socket.onclose = null;
    this.socket.onmessage = null;
    this.socket.close();
    this.socket = undefined;
  }

  /** Opens the stream; resolves true once open, false if it closed or timed out first. */
  private openSocket(streamUrl: string, timeoutMs?: number): Promise<boolean> {
    const WS = this.WebSocketImpl!;
    const socket = new WS(streamUrl);
    this.socket = socket;
    let settle: (opened: boolean) => void = () => undefined;
    const result = new Promise<boolean>((resolve) => {
      let done = false;
      settle = (opened) => {
        if (done) return;
        done = true;
        resolve(opened);
      };
    });
    const timer = timeoutMs ? this.setTimer(() => settle(false), timeoutMs) : undefined;
    socket.onopen = () => {
      if (timer) this.clearTimer(timer);
      this.reconnectAttempts = 0;
      this.setStatus('online');
      settle(true);
    };
    socket.onmessage = (event: MessageEvent) => {
      const data = typeof event.data === 'string' ? event.data : '';
      if (!data) return; // keep-alive
      try {
        this.ingest(JSON.parse(data) as ActivitySet);
      } catch (err) {
        console.warn('[agent-widget] ignoring malformed Direct Line frame', err);
      }
    };
    socket.onclose = () => {
      if (timer) this.clearTimer(timer);
      const wasOpen = this.status === 'online' || this.status === 'reconnecting';
      settle(false);
      if (this.ended || this.socket !== socket) return;
      if (wasOpen || !timeoutMs) this.scheduleReconnect();
    };
    socket.onerror = () => {
      // onclose follows; reconnect is handled there.
    };
    return result;
  }

  private ingest(set: ActivitySet): void {
    if (set.watermark) this.watermark = set.watermark;
    for (const activity of set.activities ?? []) this.activities.emit(activity);
  }

  private scheduleReconnect(): void {
    const max = this.options.maxReconnectAttempts ?? 8;
    if (this.reconnectAttempts >= max) {
      this.setStatus('failed', 'reconnect attempts exhausted');
      return;
    }
    this.setStatus('reconnecting');
    const delay = Math.min(30_000, 1000 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.reconnectTimer = this.setTimer(() => void this.reconnect(), delay);
  }

  private async reconnect(): Promise<void> {
    if (this.ended || !this.convId) return;
    try {
      const query = this.watermark ? `?watermark=${encodeURIComponent(this.watermark)}` : '';
      const conversation = await this.request<ConversationResponse>(
        'GET',
        `/conversations/${encodeURIComponent(this.convId)}${query}`,
      );
      if (conversation.token) this.token = conversation.token;
      if (conversation.streamUrl) void this.openSocket(conversation.streamUrl);
      else this.scheduleReconnect();
    } catch (err) {
      if (err instanceof HttpError && (err.status === 401 || err.status === 403)) {
        try {
          await this.refreshToken();
        } catch {
          return; // status already set to expiredToken
        }
      }
      this.scheduleReconnect();
    }
  }

  private poll(): void {
    if (this.ended || !this.convId) return;
    const interval = this.options.pollingInterval ?? 1000;
    const query = this.watermark ? `?watermark=${encodeURIComponent(this.watermark)}` : '';
    this.request<ActivitySet>('GET', `/conversations/${encodeURIComponent(this.convId)}/activities${query}`)
      .then((set) => {
        this.pollFailures = 0;
        this.ingest(set);
      })
      .catch((err) => {
        this.pollFailures += 1;
        if (err instanceof HttpError && (err.status === 401 || err.status === 403)) return this.refreshToken();
        return undefined;
      })
      .catch(() => undefined)
      .finally(() => {
        if (this.ended || this.status === 'expiredToken') return;
        if (this.pollFailures >= 10) {
          this.setStatus('failed', 'polling failed repeatedly');
          return;
        }
        this.pollTimer = this.setTimer(() => this.poll(), interval * (this.pollFailures ? 2 : 1));
      });
  }

  private scheduleRefresh(expiresIn: number | undefined): void {
    if (this.refreshTimer) this.clearTimer(this.refreshTimer);
    const seconds = Math.max(30, (expiresIn ?? 1800) - 120);
    this.refreshTimer = this.setTimer(() => {
      this.refreshToken().catch(() => undefined);
    }, seconds * 1000);
  }

  /**
   * Refreshes the conversation token. Direct Line tokens are bound to one conversation, so the
   * standard path is Direct Line's own /tokens/refresh with the current token. If that fails
   * (token already expired), the portal backend is asked via getToken({ reason: 'refresh' }),
   * which can reconnect to the conversation server-side.
   */
  private refreshToken(): Promise<void> {
    this.refreshing ??= this.doRefresh().finally(() => {
      this.refreshing = undefined;
    });
    return this.refreshing;
  }

  private async doRefresh(): Promise<void> {
    try {
      const res = await this.request<{ token?: string; expires_in?: number }>('POST', '/tokens/refresh');
      if (!res.token) throw new Error('no token in refresh response');
      this.token = res.token;
      this.scheduleRefresh(res.expires_in);
      return;
    } catch {
      // fall through to the portal backend
    }
    try {
      const res = await this.options.getToken({ reason: 'refresh', conversationId: this.convId });
      this.token = res.token;
      if (res.userId) this.userIdValue = res.userId;
      this.scheduleRefresh(res.expires_in);
    } catch (err) {
      this.setStatus('expiredToken', err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  private clearAllTimers(): void {
    for (const t of [this.refreshTimer, this.pollTimer, this.reconnectTimer]) if (t) this.clearTimer(t);
  }
}

/** Builds a getToken function that POSTs to a portal backend endpoint with cookies. */
export function tokenUrlFetcher(url: string, fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis)) {
  return async (request: TokenRequest): Promise<DirectLineTokenResponse> => {
    const res = await fetchImpl(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (!res.ok) throw new Error(`Token endpoint failed (${res.status})`);
    const json = (await res.json()) as DirectLineTokenResponse;
    if (!json.token) throw new Error('Token endpoint returned no token');
    return json;
  };
}
