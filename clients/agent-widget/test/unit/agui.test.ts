import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AgUiTransport, type AgUiEvent } from '../../src/core/agui';
import type { Activity, TokenRequest } from '../../src/types';

const ENDPOINT = 'https://relay.example/agui';
const THREAD = 'thr_abc';

function sseBody(events: AgUiEvent[]): ReadableStream<Uint8Array> {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      // Split mid-frame to prove the parser buffers across chunks.
      controller.enqueue(bytes.slice(0, 17));
      controller.enqueue(bytes.slice(17));
      controller.close();
    },
  });
}

function setup(runs: AgUiEvent[][], options: { snapshot?: unknown; firstStatus?: number } = {}) {
  const bodies: Array<Record<string, unknown>> = [];
  const tokenRequests: TokenRequest[] = [];
  const auths: string[] = [];
  let tokenN = 0;
  let first = true;
  const fetchImpl = (async (url: string, init: RequestInit = {}) => {
    auths.push((init.headers as Record<string, string>).Authorization);
    if (url === `${ENDPOINT}/threads/${THREAD}`) {
      return { ok: true, status: 200, json: async () => options.snapshot } as Response;
    }
    assert.equal(url, `${ENDPOINT}/run`);
    if (first && options.firstStatus) {
      first = false;
      return { ok: false, status: options.firstStatus, body: null } as unknown as Response;
    }
    bodies.push(JSON.parse(String(init.body)));
    const events = runs.shift() ?? [{ type: 'RUN_STARTED' }, { type: 'RUN_FINISHED', outcome: { type: 'success' } }];
    return { ok: true, status: 200, body: sseBody(events) } as unknown as Response;
  }) as typeof fetch;
  const transport = new AgUiTransport({
    endpoint: ENDPOINT,
    fetchImpl,
    setTimeoutImpl: (() => 0) as unknown as typeof setTimeout,
    clearTimeoutImpl: (() => undefined) as unknown as typeof clearTimeout,
    getToken: async (req) => {
      tokenRequests.push(req);
      tokenN += 1;
      return { token: `tok${tokenN}`, conversationId: THREAD, userId: 'agui_u1', expires_in: 1800 };
    },
  });
  const seen: Activity[] = [];
  transport.onActivity((a) => seen.push(a));
  return { transport, bodies, seen, tokenRequests, auths };
}

const settle = () => new Promise((r) => setTimeout(r, 20));
const user = { id: 'w-user', role: 'user' as const };

test('connect uses the token response as the thread', async () => {
  const { transport, tokenRequests } = setup([]);
  await transport.connect({ userId: 'w-user' });
  assert.equal(transport.conversationId, THREAD);
  assert.equal(transport.userId, 'agui_u1');
  assert.deepEqual(tokenRequests[0], { reason: 'start', conversationId: undefined });
});

test('a text turn becomes one RunAgentInput and maps events to activities', async () => {
  const card = { type: 'AdaptiveCard', version: '1.5', body: [] };
  const { transport, bodies, seen } = setup([
    [
      { type: 'RUN_STARTED', threadId: THREAD, runId: 'r1' },
      { type: 'STEP_STARTED', stepName: 'Checking your plan…' },
      { type: 'STEP_FINISHED', stepName: 'Checking your plan…' },
      { type: 'TEXT_MESSAGE_START', messageId: 'm1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'Yes, ' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: "it's covered." },
      { type: 'TEXT_MESSAGE_END', messageId: 'm1' },
      { type: 'ACTIVITY_SNAPSHOT', messageId: 'c1', activityType: 'result_chip', content: { text: 'Plan reviewed', state: 'done' } },
      { type: 'STATE_DELTA', delta: [{ op: 'add', path: '/breadcrumb', value: 'Benefit check' }] },
      { type: 'ACTIVITY_SNAPSHOT', messageId: 'a1', activityType: 'adaptive_card', content: { templateId: 'benefit-coverage@1', card } },
      { type: 'ACTIVITY_SNAPSHOT', messageId: 's1', activityType: 'suggestions', content: { actions: [{ title: 'Find dermatologists', value: 'Find dermatologists', recommended: true }] } },
      { type: 'CUSTOM', name: 'navigate', value: { route: '/plan/benefits' } },
      { type: 'RUN_FINISHED', threadId: THREAD, runId: 'r1', outcome: { type: 'success' } },
    ],
  ]);
  await transport.connect({ userId: 'w-user' });
  await transport.post({ type: 'event', name: 'context', from: user, value: { locale: 'en-US', page: { route: '/benefits' } } });
  assert.equal(bodies.length, 0, 'context is kept for the next run, not sent alone');
  await transport.post({ type: 'message', from: user, text: 'Is a skin check covered?' });
  await settle();

  const input = bodies[0];
  assert.equal(input.threadId, THREAD);
  assert.deepEqual((input.messages as Array<{ role: string; content: string }>).map((m) => [m.role, m.content]), [['user', 'Is a skin check covered?']]);
  assert.deepEqual(input.context, [{ description: 'page', value: '/benefits' }, { description: 'locale', value: 'en-US' }]);
  assert.equal(input.resume, undefined);

  const kinds = seen.map((a) => `${a.type}:${a.entities?.[0] && (a.entities[0] as { streamType?: string }).streamType ? (a.entities[0] as { streamType: string }).streamType : a.name ?? ''}`);
  assert.deepEqual(kinds, ['typing:informative', 'typing:streaming', 'typing:streaming', 'message:final', 'event:navigate', 'message:']);
  const text = seen[3];
  assert.equal(text.text, "Yes, it's covered.");
  assert.deepEqual(text.channelData?.resultChip, { text: 'Plan reviewed', state: 'done' });
  assert.equal(text.channelData?.breadcrumb, 'Benefit check');
  const cardMsg = seen[5];
  assert.equal(cardMsg.attachments?.[0].contentType, 'application/vnd.microsoft.card.adaptive');
  assert.equal(cardMsg.channelData?.templateId, 'benefit-coverage@1');
  assert.deepEqual(cardMsg.suggestedActions?.actions[0], { type: 'imBack', title: 'Find dermatologists', value: 'Find dermatologists', channelData: { recommended: true } });
});

test('a review card interrupt is answered by Confirm and cancelled by anything else', async () => {
  const interrupt = { id: 'act_1', reason: 'confirmation', message: 'Nothing is booked until you confirm.' };
  const { transport, bodies } = setup([
    [{ type: 'RUN_STARTED' }, { type: 'RUN_FINISHED', outcome: { type: 'interrupt', interrupts: [interrupt] } }],
    [{ type: 'RUN_STARTED' }, { type: 'RUN_FINISHED', outcome: { type: 'interrupt', interrupts: [{ ...interrupt, id: 'act_2' }] } }],
    [{ type: 'RUN_STARTED' }, { type: 'RUN_FINISHED', outcome: { type: 'success' } }],
  ]);
  await transport.connect({ userId: 'w-user' });
  await transport.post({ type: 'message', from: user, value: { action: { type: 'Action.Execute', verb: 'appointment.review', data: { providerRef: 'prv_19' } } } });
  await settle();
  assert.deepEqual(bodies[0].forwardedProps, { action: { verb: 'appointment.review', data: { providerRef: 'prv_19' } } });
  assert.deepEqual(transport.pendingInterrupts.map((i) => i.id), ['act_1']);

  // "Change time" while the review is open: the action goes through and the interrupt is cancelled.
  await transport.post({ type: 'message', from: user, value: { action: { type: 'Action.Execute', verb: 'appointment.availability', data: { providerRef: 'prv_19' } } } });
  await settle();
  assert.deepEqual(bodies[1].resume, [{ interruptId: 'act_1', status: 'cancelled' }]);
  assert.deepEqual(transport.pendingInterrupts.map((i) => i.id), ['act_2']);

  // Confirm on the new review card resumes its interrupt with the office note.
  await transport.post({ type: 'message', from: user, value: { action: { type: 'Action.Execute', verb: 'appointment.confirm', data: { actionId: 'act_2', officeNote: 'left shoulder' } } } });
  await settle();
  assert.deepEqual(bodies[2].resume, [{ interruptId: 'act_2', status: 'resolved', payload: { approved: true, note: 'left shoulder' } }]);
  assert.deepEqual(bodies[2].forwardedProps, {});
  assert.equal(transport.pendingInterrupts.length, 0);
});

test('referral submit carries the attestation', async () => {
  const { transport, bodies } = setup([[{ type: 'RUN_FINISHED', outcome: { type: 'interrupt', interrupts: [{ id: 'act_r' }] } }]]);
  await transport.connect({ userId: 'w-user' });
  await transport.post({ type: 'message', from: user, value: { action: { verb: 'referral.review', data: {} } } });
  await settle();
  await transport.post({ type: 'message', from: user, value: { action: { verb: 'referral.submit', data: { actionId: 'act_r', attest: 'true', clinicalNote: 'changing mole' } } } });
  await settle();
  assert.deepEqual(bodies[1].resume, [{ interruptId: 'act_r', status: 'resolved', payload: { approved: true, note: 'changing mole', attest: true } }]);
});

test('journeys and hand-off become forwardedProps', async () => {
  const { transport, bodies } = setup([]);
  await transport.connect({ userId: 'w-user' });
  await transport.post({ type: 'event', name: 'startJourney', from: user, value: { journeyId: 'doctor-search', params: { zip: '10013' } } });
  await transport.post({ type: 'event', name: 'handoffRequest', from: user, value: {} });
  await settle();
  assert.deepEqual(bodies[0].forwardedProps, { journey: { id: 'doctor-search', params: { zip: '10013' } } });
  assert.deepEqual(bodies[1].forwardedProps, { action: { verb: 'handoff' } });
});

test('a 401 refreshes the token once and retries', async () => {
  const { transport, bodies, tokenRequests, auths } = setup([], { firstStatus: 401 });
  await transport.connect({ userId: 'w-user' });
  await transport.post({ type: 'message', from: user, text: 'hi' });
  await settle();
  assert.equal(bodies.length, 1);
  assert.deepEqual(tokenRequests.map((r) => r.reason), ['start', 'refresh']);
  assert.deepEqual(auths, ['Bearer tok1', 'Bearer tok2']);
});

test('resume restores the transcript and open interrupts', async () => {
  const card = { type: 'AdaptiveCard', version: '1.5', body: [] };
  const { transport, seen, tokenRequests, bodies } = setup([], {
    snapshot: {
      messages: [
        { id: 'u1', role: 'user', content: 'book it' },
        { id: 'm1', role: 'assistant', content: 'Check the details, then confirm.' },
        { id: 'a1', role: 'activity', activityType: 'adaptive_card', content: { templateId: 'booking-review@1', card } },
      ],
      interrupts: [{ id: 'act_9', reason: 'confirmation' }],
      state: { breadcrumb: 'Appointment review' },
    },
  });
  await transport.connect({ userId: 'w-user', resumeConversationId: THREAD });
  assert.deepEqual(tokenRequests[0], { reason: 'resume', conversationId: THREAD });
  assert.deepEqual(seen.map((a) => [a.from.role, a.text ?? a.channelData?.templateId]), [
    ['user', 'book it'],
    ['bot', 'Check the details, then confirm.'],
    ['bot', 'booking-review@1'],
  ]);
  await transport.post({ type: 'message', from: user, value: { action: { verb: 'appointment.confirm', data: { actionId: 'act_9' } } } });
  await settle();
  assert.deepEqual(bodies[0].resume, [{ interruptId: 'act_9', status: 'resolved', payload: { approved: true } }]);
});

test('turns stay ordered: a second post waits for the first stream to end', async () => {
  const { transport, seen } = setup([
    [{ type: 'TEXT_MESSAGE_START', messageId: 'first' }, { type: 'TEXT_MESSAGE_CONTENT', messageId: 'first', delta: 'one' }, { type: 'TEXT_MESSAGE_END', messageId: 'first' }, { type: 'RUN_FINISHED' }],
    [{ type: 'TEXT_MESSAGE_START', messageId: 'second' }, { type: 'TEXT_MESSAGE_CONTENT', messageId: 'second', delta: 'two' }, { type: 'TEXT_MESSAGE_END', messageId: 'second' }, { type: 'RUN_FINISHED' }],
  ]);
  await transport.connect({ userId: 'w-user' });
  await Promise.all([transport.post({ type: 'message', from: user, text: 'a' }), transport.post({ type: 'message', from: user, text: 'b' })]);
  await settle();
  assert.deepEqual(seen.filter((a) => a.type === 'message').map((a) => a.text), ['one', 'two']);
});
