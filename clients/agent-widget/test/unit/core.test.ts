import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ConversationStore } from '../../src/core/conversation';
import { extractRefs, initialsOf, isRouteAllowed, isUrlAllowed } from '../../src/core/policy';
import { expandTemplate, evaluate } from '../../src/mock/templating';
import type { Activity } from '../../src/types';
import providerResults from '../../templates/provider-results@1.json';
import benefitCoverage from '../../templates/benefit-coverage@1.json';

const bot = { id: 'bot', role: 'bot' as const };
const user = { id: 'me', role: 'user' as const };

test('templating: expressions', () => {
  const scope = { data: { a: { b: [1, 2, 3] }, audience: 'member' }, root: {} };
  assert.equal(evaluate('count(a.b)', scope), 3);
  assert.equal(evaluate("audience == 'member' && count(a.b) > 2", scope), true);
  assert.equal(evaluate("if(audience == 'provider', 'x', 'y')", scope), 'y');
});

test('templating: provider-results picks the action set by audience', () => {
  const data = {
    title: 'Doctors',
    doctors: [
      { ref: 'prv_1', initials: 'NP', name: 'Dr. A', specialty: 'Derm', practice: 'P', services: 's', network: 'n', address: 'x', distanceText: '1 mi' },
      { ref: 'prv_2', initials: 'DC', name: 'Dr. B', specialty: 'Derm', practice: 'Q', services: 's', network: 'n', address: 'y', distanceText: '2 mi' },
    ],
    plan: 'Harbor HMO',
    radius: 5,
    zip: '10012',
    selected: 'prv_1',
    audience: 'member',
    serviceRef: 'svc',
    notice: 'n',
  };
  const member = expandTemplate<{ body: Array<Record<string, unknown>>; actions: Array<{ title: string }> }>(providerResults, data);
  assert.deepEqual(member.actions.map((a) => a.title), ['Check availability', 'View doctor']);
  assert.equal(member.body[1].text, '2 matches · Harbor HMO · Within 5 miles of 10012');
  const list = member.body[2] as { items: Array<{ title: string; value: string }>; value: string };
  assert.equal(list.items.length, 2);
  assert.equal(list.items[1].value, 'prv_2');
  assert.equal(list.value, 'prv_1');

  const provider = expandTemplate<{ actions: Array<{ title: string }> }>(providerResults, { ...data, audience: 'provider' });
  assert.deepEqual(provider.actions.map((a) => a.title), ['Review referral', 'View doctor']);
});

test('templating: fact rows repeat and the card stays valid JSON', () => {
  const card = expandTemplate<{ body: Array<{ type: string; facts?: unknown[] }> }>(benefitCoverage, {
    service: { name: 'Medical skin exam', category: 'Dermatology', ref: 'svc' },
    plan: { name: 'Harbor HMO', year: '2026', ref: 'pln' },
    coverage: { label: 'Covered' },
    facts: [{ title: 'Network', value: 'In-network' }, { title: 'Visit cost', value: '$40' }],
    notice: 'n',
  });
  const factSet = card.body.find((b) => b.type === 'FactSet');
  assert.equal(factSet?.facts?.length, 2);
  assert.doesNotMatch(JSON.stringify(card), /\$\{/);
});

test('store: Agents SDK streaming (informative → streaming → final) yields one message', () => {
  const store = new ConversationStore((a) => a.from.role === 'user');
  store.apply({ type: 'typing', from: bot, text: 'Checking…', entities: [{ type: 'streaminfo', streamType: 'informative' }] });
  assert.equal(store.snapshot.progress.active, true);
  assert.equal(store.snapshot.progress.text, 'Checking…');
  store.apply({ type: 'typing', id: 's1', from: bot, text: 'Your plan', entities: [{ type: 'streaminfo', streamType: 'streaming', streamId: 's1' }] });
  store.apply({ type: 'typing', id: 's2', from: bot, text: 'Your plan covers it', entities: [{ type: 'streaminfo', streamType: 'streaming', streamId: 's1' }] });
  assert.equal(store.snapshot.items.length, 1);
  assert.equal(store.snapshot.items[0].kind === 'bot' && store.snapshot.items[0].streaming, true);
  store.apply({
    type: 'message',
    id: 'final',
    from: bot,
    text: 'Your plan covers it.',
    entities: [{ type: 'streaminfo', streamType: 'final', streamId: 's1' }],
    channelData: { resultChip: { text: 'Benefits reviewed' }, breadcrumb: 'Benefit check' },
    suggestedActions: { actions: [{ type: 'imBack', title: 'Find doctors', value: 'Find doctors' }] },
  });
  const items = store.snapshot.items;
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, 'bot');
  if (items[0].kind === 'bot') {
    assert.equal(items[0].text, 'Your plan covers it.');
    assert.equal(items[0].streaming, false);
    assert.equal(items[0].resultChip?.text, 'Benefits reviewed');
  }
  assert.equal(store.snapshot.progress.active, false);
  assert.equal(store.snapshot.breadcrumb, 'Benefit check');
  assert.equal(store.snapshot.suggestions.length, 1);
});

test('store: echo de-duplication and suggestion reset on send', () => {
  const store = new ConversationStore((a) => a.from.role === 'user');
  store.apply({ type: 'message', id: 'b1', from: bot, text: 'Hi', suggestedActions: { actions: [{ type: 'imBack', title: 'x' }] } });
  store.addLocalUser('c-1', 'Hello');
  assert.equal(store.snapshot.suggestions.length, 0);
  const echo: Activity = { type: 'message', id: 'srv-9', from: user, text: 'Hello', channelData: { clientActivityId: 'c-1' } };
  store.apply(echo);
  store.apply(echo); // replayed after reconnect
  const users = store.snapshot.items.filter((i) => i.kind === 'user');
  assert.equal(users.length, 1);
  assert.equal(users[0].kind === 'user' && users[0].status, 'sent');
  store.apply({ type: 'message', id: 'b1', from: bot, text: 'Hi' }); // duplicate bot delivery
  assert.equal(store.snapshot.items.filter((i) => i.kind === 'bot').length, 1);
});

test('policy: routes, URLs, refs and initials', () => {
  const allowed = ['/plan/*', '/providers/*', '/claims'];
  assert.equal(isRouteAllowed('/providers/prv_19', allowed), true);
  assert.equal(isRouteAllowed('/claims', allowed), true);
  assert.equal(isRouteAllowed('/claims/123', allowed), false);
  assert.equal(isRouteAllowed('//evil.example/x', allowed), false);
  assert.equal(isRouteAllowed('https://evil.example', allowed), false);
  assert.equal(isRouteAllowed('/plan/x', undefined), false);

  const origin = 'https://portal.harbor.example';
  assert.equal(isUrlAllowed('/benefits', [], origin), true);
  assert.equal(isUrlAllowed('https://docs.harbor.example/a', ['https://docs.harbor.example'], origin), true);
  assert.equal(isUrlAllowed('https://evil.example/a', ['https://docs.harbor.example'], origin), false);
  assert.equal(isUrlAllowed('javascript:alert(1)', ['https://docs.harbor.example'], origin), false);
  assert.equal(isUrlAllowed('http://docs.harbor.example/a', ['http://docs.harbor.example'], origin), false);

  assert.deepEqual(extractRefs({ providerRef: 'prv_19', slotId: 'slt_1', officeNote: 'my mole is…', zip: '10012' }), { providerRef: 'prv_19', slotId: 'slt_1' });
  assert.equal(initialsOf('Dr. Nina Patel'), 'NP');
  assert.equal(initialsOf('Alex Morgan'), 'AM');
});

test('store: user items keep a stable key and do not re-render on duplicate confirmations', () => {
  const store = new ConversationStore((a) => a.from.role === 'user');
  let notifications = 0;
  store.subscribe(() => (notifications += 1));
  store.addLocalUser('c-7', 'Hi');
  store.markSent('c-7', 'srv-1');
  const afterSend = notifications;
  const item = store.snapshot.items[0];
  assert.equal(item.id, 'c-7', 'render key stays the client id');
  assert.equal(item.kind === 'user' && item.serverId, 'srv-1');
  store.markSent('c-7', 'srv-1');
  store.apply({ type: 'message', id: 'srv-1', from: user, text: 'Hi', channelData: { clientActivityId: 'c-7' } });
  assert.equal(notifications, afterSend, 'echo and repeated confirmation cause no re-render');
  store.markFailed('c-7');
  store.markSending('c-7');
  assert.equal(store.snapshot.items[0].kind === 'user' && store.snapshot.items[0].status, 'sending');
});

test('store: streamed message keeps its key but exposes the real activity id', () => {
  const store = new ConversationStore((a) => a.from.role === 'user');
  store.apply({ type: 'typing', id: 'a1', from: bot, text: 'Hel', entities: [{ type: 'streaminfo', streamType: 'streaming', streamId: 'a1' }] });
  store.apply({ type: 'message', id: 'a9', from: bot, text: 'Hello', entities: [{ type: 'streaminfo', streamType: 'final', streamId: 'a1' }] });
  const [only] = store.snapshot.items;
  assert.equal(only.id, 'stream-a1');
  assert.equal(only.kind === 'bot' && only.activityId, 'a9', 'feedback / replyToId use the server id');
  store.setWorking();
  assert.equal(store.snapshot.progress.active, true);
  store.clearProgress();
  assert.equal(store.snapshot.progress.active, false);
});

test('theme: tokens that could break out of the stylesheet are ignored', async () => {
  const { resolveTheme, themeToCss, DEFAULT_THEME } = await import('../../src/ui/theme');
  const warn = console.warn;
  console.warn = () => undefined;
  try {
    const theme = resolveTheme('default', { brand: '#0b5cad', surface: 'red; } :host { display:none', text: 'blue}' } as never);
    assert.equal(theme.brand, '#0b5cad');
    assert.equal(theme.surface, DEFAULT_THEME.surface);
    assert.equal(theme.text, DEFAULT_THEME.text);
    assert.doesNotMatch(themeToCss(theme), /display:none/);
  } finally {
    console.warn = warn;
  }
});
