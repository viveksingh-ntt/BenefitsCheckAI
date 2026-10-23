import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DirectLineTransport } from '../../src/core/directline';
import type { Activity, TokenRequest } from '../../src/types';

const DOMAIN = 'https://dl.example/v3/directline';

class FakeSocket {
  static instances: FakeSocket[] = [];
  static neverOpen = false;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
    if (!FakeSocket.neverOpen) queueMicrotask(() => this.onopen?.());
  }
  close() {
    this.closed = true;
  }
  push(activities: Activity[], watermark: string) {
    this.onmessage?.({ data: JSON.stringify({ activities, watermark }) });
  }
}

interface Call {
  method: string;
  url: string;
  auth: string;
  body?: unknown;
}

function setup(options: { postStatuses?: number[]; dlRefresh?: boolean; socketNeverOpens?: boolean } = {}) {
  const calls: Call[] = [];
  const tokenRequests: TokenRequest[] = [];
  const timers: Array<{ fn: () => void; ms: number }> = [];
  const postStatuses = [...(options.postStatuses ?? [])];
  let tokenN = 0;
  FakeSocket.instances = [];
  FakeSocket.neverOpen = Boolean(options.socketNeverOpens);

  const fetchImpl = (async (url: string, init: RequestInit) => {
    const auth = (init.headers as Record<string, string>).Authorization;
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method: init.method ?? 'GET', url, auth, body });
    const json = (status: number, payload: unknown) =>
      ({ ok: status < 300, status, text: async () => JSON.stringify(payload), json: async () => payload }) as Response;
    if (url === `${DOMAIN}/conversations` && init.method === 'POST') {
      return json(201, { conversationId: 'conv1', token: 'conv-token', expires_in: 1800, streamUrl: 'wss://dl.example/stream?t=1' });
    }
    if (url.startsWith(`${DOMAIN}/conversations/conv1?`) || url === `${DOMAIN}/conversations/conv1`) {
      return json(200, { conversationId: 'conv1', token: 'conv-token-2', streamUrl: 'wss://dl.example/stream?t=2' });
    }
    if (url === `${DOMAIN}/tokens/refresh` && options.dlRefresh) {
      return json(200, { conversationId: 'conv1', token: 'dl-refreshed', expires_in: 1800 });
    }
    if (url.startsWith(`${DOMAIN}/conversations/conv1/activities`) && (init.method ?? 'GET') === 'GET') {
      return json(200, { activities: [{ type: 'message', id: 'p1', from: { id: 'bot' }, text: 'polled' }], watermark: '1' });
    }
    if (url === `${DOMAIN}/conversations/conv1/activities`) {
      const status = postStatuses.shift() ?? 200;
      return json(status, status === 200 ? { id: 'conv1|0001' } : {});
    }
    return json(404, {});
  }) as unknown as typeof fetch;

  const transport = new DirectLineTransport({
    domain: DOMAIN,
    getToken: async (req) => {
      tokenRequests.push(req);
      tokenN += 1;
      return { token: `portal-token-${tokenN}`, expires_in: 1800 };
    },
    fetchImpl,
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    setTimeoutImpl: ((fn: () => void, ms: number) => {
      timers.push({ fn, ms });
      return timers.length as unknown as ReturnType<typeof setTimeout>;
    }) as unknown as typeof setTimeout,
    clearTimeoutImpl: (() => undefined) as unknown as typeof clearTimeout,
  });
  return { transport, calls, tokenRequests, timers };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

test('directline: starts a conversation with the portal token and streams activities', async () => {
  const { transport, calls, tokenRequests } = setup();
  const statuses: string[] = [];
  const received: Activity[] = [];
  transport.onStatus((s) => statuses.push(s));
  transport.onActivity((a) => received.push(a));
  await transport.connect({ userId: 'u1' });
  await flush();

  assert.deepEqual(tokenRequests[0], { reason: 'start', conversationId: undefined });
  assert.equal(calls[0].url, `${DOMAIN}/conversations`);
  assert.equal(calls[0].auth, 'Bearer portal-token-1');
  assert.equal(transport.conversationId, 'conv1');
  assert.deepEqual(statuses, ['connecting', 'online']);

  FakeSocket.instances[0].push([{ type: 'message', from: { id: 'bot' }, text: 'hi' }], '1');
  FakeSocket.instances[0].onmessage?.({ data: '' }); // keep-alive frame
  assert.equal(received.length, 1);

  const id = await transport.post({ type: 'message', from: { id: 'ignored', role: 'user' }, text: 'Hello' });
  assert.equal(id, 'conv1|0001');
  const post = calls.at(-1)!;
  assert.equal(post.auth, 'Bearer conv-token');
  assert.equal((post.body as Activity).from.id, 'u1');
});

test('directline: falls back to the portal backend when Direct Line refresh fails', async () => {
  const { transport, tokenRequests, timers } = setup();
  await transport.connect({ userId: 'u1' });
  const refresh = timers.find((t) => t.ms === (1800 - 120) * 1000);
  assert.ok(refresh, 'refresh timer scheduled at expires_in - 120s');
  refresh.fn();
  await flush();
  assert.deepEqual(tokenRequests[1], { reason: 'refresh', conversationId: 'conv1' });
});

test('directline: reconnects with a fresh stream URL from the last watermark', async () => {
  const { transport, calls, timers } = setup();
  const statuses: string[] = [];
  transport.onStatus((s) => statuses.push(s));
  await transport.connect({ userId: 'u1' });
  await flush();
  FakeSocket.instances[0].push([], '7');
  FakeSocket.instances[0].onclose?.();
  assert.equal(statuses.at(-1), 'reconnecting');
  const backoff = timers.find((t) => t.ms === 1000);
  assert.ok(backoff, 'first reconnect after 1s');
  backoff.fn();
  await flush();
  await flush();
  assert.equal(calls.at(-1)!.url, `${DOMAIN}/conversations/conv1?watermark=7`);
  assert.equal(FakeSocket.instances[1].url, 'wss://dl.example/stream?t=2');
  await flush();
  assert.equal(statuses.at(-1), 'online');
});

test('directline: a 403 on post refreshes the token once and retries', async () => {
  const { transport, calls, tokenRequests } = setup({ postStatuses: [403, 200] });
  await transport.connect({ userId: 'u1' });
  const id = await transport.post({ type: 'message', from: { id: 'u1' }, text: 'x' });
  assert.equal(id, 'conv1|0001');
  assert.equal(tokenRequests.at(-1)?.reason, 'refresh');
  const posts = calls.filter((c) => c.url.endsWith('/activities'));
  assert.equal(posts.length, 2);
  assert.equal(posts[1].auth, 'Bearer portal-token-2');
});

test('directline: end() closes the socket and stops reconnecting', async () => {
  const { transport } = setup();
  const statuses: string[] = [];
  transport.onStatus((s) => statuses.push(s));
  await transport.connect({ userId: 'u1' });
  transport.end();
  assert.equal(FakeSocket.instances[0].closed, true);
  assert.equal(statuses.at(-1), 'ended');
});

test('directline: refreshes through Direct Line /tokens/refresh without calling the portal', async () => {
  const { transport, calls, tokenRequests, timers } = setup({ dlRefresh: true });
  await transport.connect({ userId: 'u1' });
  timers.find((t) => t.ms === (1800 - 120) * 1000)!.fn();
  await flush();
  assert.equal(tokenRequests.length, 1, 'portal only asked for the start token');
  const refresh = calls.find((c) => c.url.endsWith('/tokens/refresh'))!;
  assert.equal(refresh.auth, 'Bearer conv-token');
  await transport.post({ type: 'message', from: { id: 'u1' }, text: 'x' });
  assert.equal(calls.at(-1)!.auth, 'Bearer dl-refreshed');
});

test('directline: falls back to HTTP polling when the WebSocket never opens', async () => {
  const { transport, calls, timers } = setup({ socketNeverOpens: true });
  const received: Activity[] = [];
  const statuses: string[] = [];
  transport.onActivity((a) => received.push(a));
  transport.onStatus((s) => statuses.push(s));
  const connecting = transport.connect({ userId: 'u1' });
  await flush();
  const openTimeout = timers.find((t) => t.ms === 10_000);
  assert.ok(openTimeout, 'socket open timeout scheduled');
  openTimeout.fn();
  await connecting;
  await flush();
  assert.equal(FakeSocket.instances[0].closed, true, 'stalled socket closed');
  assert.ok(calls.some((c) => c.url.startsWith(`${DOMAIN}/conversations/conv1/activities`) && c.method === 'GET'), 'polling started');
  assert.equal(received[0]?.text, 'polled');
  assert.equal(statuses.at(-1), 'online');
});
