// End-to-end check of the widget against the mock relay, in headless Chromium.
// Walks every prototype journey, asserts behaviour, and writes screenshots to test/e2e/screens/.
//   npm run test:e2e
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { startServer } from '../../scripts/serve.mjs';

const PORT = 5174;
const OUT = 'test/e2e/screens';
mkdirSync(OUT, { recursive: true });

const server = await startServer(PORT);
const browser = await chromium.launch();
const errors = [];
let step = '';
const results = [];

async function check(name, fn) {
  step = name;
  await fn();
  results.push(name);
  console.log(`  ✓ ${name}`);
}

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  page.on('pageerror', (e) => errors.push(`${step}: ${e.message}`));
  page.on('console', (m) => m.type() === 'error' && !/fonts\.(googleapis|gstatic)/.test(m.location().url ?? '') && errors.push(`${step}: ${m.text()}`));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort()); // offline sandbox
  await page.goto(`http://localhost:${PORT}/demo/`);

  const widget = page.locator('agent-widget');
  const panel = widget.locator('.aw-panel');
  const log = page.locator('#event-log');
  const lastCard = () => widget.locator('.aw-card').last();

  await check('ready event and member context header', async () => {
    await page.waitForFunction(() => document.querySelector('#event-log')?.textContent?.includes('ready'));
    await assert.doesNotReject(widget.locator('.aw-context-name', { hasText: 'Alex Morgan · Your plan' }).waitFor());
    assert.equal(await widget.locator('.aw-context-meta').textContent(), 'Harbor HMO · ID ending 4821 · Active');
  });

  await check('screen 2: benefit check card, result chip and next-step chips', async () => {
    await lastCard().getByText('Covered when medically necessary').waitFor();
    await widget.getByText('Plan eligibility and benefits reviewed').waitFor();
    await widget.locator('.aw-chip', { hasText: 'View plan details' }).waitFor();
    assert.equal(await widget.locator('.aw-chip').count(), 4);
    assert.equal(await lastCard().locator('.ac-facts dt').count(), 5);
    assert.match(await widget.locator('.aw-crumb-text').textContent(), /Member · Benefit check/);
    await page.waitForTimeout(300);
    await panel.screenshot({ path: `${OUT}/screen-2-benefit-check.png` });
  });

  await check('card action posts to relay, marks card answered, opens screen 3', async () => {
    await lastCard().getByRole('button', { name: 'Find this service' }).click();
    await widget.locator('.aw-card').filter({ hasText: 'Medical skin exam options' }).waitFor();
    const first = widget.locator('.aw-card').first();
    assert.equal(await first.getByRole('button', { name: 'Find this service' }).isDisabled(), true);
    await first.locator('.aw-card-status', { hasText: 'Find this service' }).waitFor();
    assert.match(await log.textContent(), /service\.find/);
    await widget.locator('.aw-chip.is-recommended', { hasText: 'Find doctors' }).waitFor();
    await page.waitForTimeout(300);
    await panel.screenshot({ path: `${OUT}/screen-3-service-search.png` });
  });

  await check('input validation blocks submit and focuses the field', async () => {
    const card = lastCard();
    const zip = card.getByLabel('ZIP code');
    await zip.fill('123');
    await card.getByRole('button', { name: 'Find doctors' }).click();
    await card.getByText('Enter a 5-digit ZIP code.').waitFor();
    assert.equal(await zip.evaluate((el) => el === el.getRootNode().activeElement), true);
    assert.equal(await zip.getAttribute('aria-invalid'), 'true');
    await zip.fill('10012');
    await card.getByLabel('Distance').selectOption('5');
    assert.equal(await card.getByRole('radio', { name: /Focused skin exam/ }).isChecked(), true);
  });

  await check('screen 4: member doctor search with selectable list', async () => {
    await lastCard().getByRole('button', { name: 'Find doctors' }).click();
    const doctors = widget.locator('.aw-card').filter({ hasText: 'Doctors for a focused skin exam' });
    await doctors.waitFor();
    await doctors.getByRole('button', { name: 'Check availability' }).waitFor();
    assert.equal(await doctors.getByRole('button', { name: 'Review referral' }).count(), 0);
    assert.equal(await doctors.getByRole('radio').count(), 2);
    await doctors.getByText('2 matches · Harbor HMO · Within 5 miles of 10012').waitFor();
    await widget.locator('.aw-chip', { hasText: 'View Dr. Patel' }).waitFor();
    await page.waitForTimeout(300);
    await panel.screenshot({ path: `${OUT}/screen-4-doctor-search-member.png` });
  });

  await check('keyboard selection and navigate event (allowlisted route)', async () => {
    const doctors = lastCard();
    await doctors.getByRole('radio', { name: /Dr\. Nina Patel/ }).focus();
    await page.keyboard.press('ArrowDown');
    assert.equal(await doctors.getByRole('radio', { name: /Dr\. Daniel Chen/ }).isChecked(), true);
    assert.equal(await doctors.locator('.ac-option.is-selected').textContent().then((t) => t.includes('Chen')), true);
    await doctors.getByRole('button', { name: 'View doctor' }).click();
    await page.waitForFunction(() => document.querySelector('#event-log')?.textContent?.includes('/providers/prv_42'));
    await page.locator('#toast', { hasText: 'Portal would open /providers/prv_42' }).waitFor();
    assert.equal(await doctors.getByRole('button', { name: 'Check availability' }).isDisabled(), false, 'navigation keeps the card active');
  });

  await check('booking HITL: availability → review → confirm', async () => {
    await lastCard().getByRole('button', { name: 'Check availability' }).click();
    const slots = widget.locator('.aw-card').filter({ hasText: 'Available times' });
    await slots.waitFor();
    await slots.getByText('Dr. Daniel Chen · Union Dermatology').waitFor();
    await slots.getByRole('radio', { name: /2:15 PM/ }).check();
    await slots.getByRole('button', { name: 'Review booking' }).click();
    const review = widget.locator('.aw-card').filter({ hasText: 'Review your appointment request' });
    await review.waitFor();
    await review.getByText('Thu, Oct 15 · 2:15 PM').waitFor();
    await review.getByLabel('Note for the office (optional)').fill('Mole on left shoulder');
    await review.getByRole('button', { name: 'Confirm booking' }).click();
    await widget.locator('.aw-card').filter({ hasText: 'Request sent (illustrative)' }).waitFor();
    // The note is PHI: it must not leak into the host action event.
    assert.doesNotMatch(await log.textContent(), /left shoulder/);
    assert.match(await log.textContent(), /appointment\.confirm/);
  });

  await check('typed questions and suggestion chips', async () => {
    await widget.locator('.aw-chip', { hasText: 'Compare copays' }).click();
    await widget.locator('.aw-bot-text li', { hasText: 'Specialist (dermatology)' }).waitFor();
    const input = widget.getByRole('textbox', { name: /Ask a question/ });
    await input.fill('What are the referral rules?');
    await input.press('Enter');
    await widget.getByText('Referrals usually last 90 days', { exact: false }).waitFor();
  });

  await check('hand-off: Get support raises a handoff event', async () => {
    await widget.getByRole('button', { name: 'Get support' }).click();
    await page.waitForFunction(() => document.querySelector('#event-log')?.textContent?.includes('HO-2741'));
  });

  await check('screen 1: provider portal, new thread, review referral', async () => {
    await page.getByRole('button', { name: 'Provider portal' }).click();
    await widget.locator('.aw-context-name', { hasText: 'Selected member: Alex Morgan' }).waitFor();
    const doctors = widget.locator('.aw-card').filter({ hasText: 'Doctors for a focused skin exam' });
    await doctors.waitFor();
    assert.equal(await widget.locator('.aw-card').count(), 1, 'previous conversation cleared');
    await doctors.getByRole('button', { name: 'Review referral' }).waitFor();
    await widget.getByText('Member network and service matched').waitFor();
    await widget.getByText('Review referral prepares details for approval', { exact: false }).waitFor();
    assert.match(await widget.locator('.aw-crumb-text').textContent(), /Provider · Doctor search/);
    await page.waitForTimeout(300);
    await panel.screenshot({ path: `${OUT}/screen-1-doctor-search-provider.png` });
  });

  await check('referral HITL: required attestation, then submit', async () => {
    await lastCard().getByRole('button', { name: 'Review referral' }).click();
    const referral = widget.locator('.aw-card').filter({ hasText: 'Referral for review' });
    await referral.waitFor();
    await referral.getByRole('button', { name: 'Submit referral' }).click();
    await referral.getByText('Confirm medical necessity to submit.').waitFor();
    await referral.getByRole('checkbox', { name: /medically necessary/ }).check();
    await referral.getByRole('button', { name: 'Submit referral' }).click();
    await widget.locator('.aw-card').filter({ hasText: 'RF-20261013-0042' }).waitFor();
    await page.waitForTimeout(300);
    await panel.screenshot({ path: `${OUT}/flow-referral-submitted.png` });
  });

  await check('switching member starts a fresh conversation', async () => {
    await page.locator('#member-select').selectOption('mbr_2c91');
    await widget.locator('.aw-context-name', { hasText: 'Selected member: Jordan Lee' }).waitFor();
    await page.waitForFunction(() => document.querySelector('agent-widget').shadowRoot.querySelectorAll('.aw-card').length === 0);
  });

  await check('deep link: startJourney(doctor-search) without a prompt', async () => {
    await page.getByRole('button', { name: /Doctor search/ }).click();
    await widget.locator('.aw-card').filter({ hasText: 'Doctors for a focused skin exam' }).waitFor();
    await widget.getByText('match Jordan’s plan', { exact: false }).waitFor();
  });

  await check('a11y basics: log region, labelled controls, Escape does not close inline mode', async () => {
    assert.equal(await widget.locator('[role="log"]').count(), 1);
    const unlabeled = await widget.evaluate((el) =>
      [...el.shadowRoot.querySelectorAll('button')].filter((b) => !b.hidden && b.offsetParent && !(b.getAttribute('aria-label') || b.textContent.trim())).length,
    );
    assert.equal(unlabeled, 0, 'every visible button has an accessible name');
    await page.keyboard.press('Escape');
    assert.equal(await panel.isVisible(), true);
  });

  await check('inline widget does not steal focus or fire open on page load', async () => {
    const fresh = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await fresh.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await fresh.goto(`http://localhost:${PORT}/demo/`);
    await fresh.waitForFunction(() => document.querySelector('#event-log')?.textContent?.includes('ready'));
    assert.equal(await fresh.evaluate(() => document.activeElement === document.body), true, 'focus stays on the page');
    assert.doesNotMatch(await fresh.locator('#event-log').textContent(), /\bopen\b/);
    assert.equal(await fresh.locator('agent-widget').locator('.aw-panel').getAttribute('role'), 'region');
    await fresh.close();
  });

  // Helper: a standalone widget on a blank page with a configurable mock relay.
  async function sandbox(mockOptions) {
    const p = await browser.newPage({ viewport: { width: 420, height: 800 } });
    p.on('pageerror', (e) => errors.push(`sandbox: ${e.message}`));
    await p.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await p.goto(`http://localhost:${PORT}/demo/blank.html`);
    await p.evaluate((opts) => {
      window.__events = [];
      window.__unhandled = [];
      window.addEventListener('unhandledrejection', (e) => window.__unhandled.push(String(e.reason)));
      const w = document.createElement('agent-widget');
      w.setAttribute('mode', 'inline');
      w.setAttribute('locale', 'en-US');
      w.style.height = '760px';
      document.body.append(w);
      ['error', 'navigate', 'handoff'].forEach((n) => w.addEventListener(n, (e) => window.__events.push([n, e.detail])));
      const shared = opts.failConnects ? { remaining: opts.failConnects } : undefined;
      w.init({
        transport: () => new AgentWidgetMock.MockRelayTransport({ speed: 0.2, failMessagePosts: opts.failMessagePosts, failConnects: shared, connectDelayMs: opts.connectDelayMs }),
        context: { member: { ref: 'mbr_7f3a', displayName: 'Alex Morgan', planName: 'Harbor HMO', idLast4: '4821', status: 'Active' } },
      });
      window.__widget = w;
    }, mockOptions);
    return p;
  }

  await check('a failed send keeps the message with Retry, and Retry delivers it', async () => {
    const p = await sandbox({ failMessagePosts: 1 });
    const w = p.locator('agent-widget');
    const input = w.getByRole('textbox');
    await input.fill('Is a skin exam covered?');
    await input.press('Enter');
    const status = w.locator('.aw-user-status.is-failed');
    await status.waitFor();
    assert.equal(await w.locator('.aw-bubble').textContent(), 'Is a skin exam covered?');
    await status.getByRole('button', { name: 'Retry' }).click();
    await w.locator('.aw-card').getByText('Covered when medically necessary').waitFor();
    assert.equal(await w.locator('.aw-user').count(), 1, 'retry reuses the same bubble');
    assert.equal(await w.locator('.aw-user-status').count(), 0, 'status line cleared once sent');
    assert.deepEqual(await p.evaluate(() => window.__unhandled), []);
    await p.close();
  });

  await check('connection failure shows a banner and its Retry reconnects', async () => {
    const p = await sandbox({ failConnects: 1 });
    const w = p.locator('agent-widget');
    const banner = w.locator('.aw-banner', { hasText: 'Can’t reach the assistant' });
    await banner.waitFor();
    await banner.getByRole('button', { name: 'Retry' }).click();
    await banner.waitFor({ state: 'hidden' });
    await w.getByRole('textbox').fill('Compare copays');
    await w.getByRole('textbox').press('Enter');
    await w.locator('.aw-bot-text li', { hasText: 'Specialist (dermatology)' }).waitFor();
    const codes = await p.evaluate(() => window.__events.filter(([n]) => n === 'error').map(([, d]) => d.code));
    assert.ok(codes.includes('connection'));
    assert.deepEqual(await p.evaluate(() => window.__unhandled), []);
    await p.close();
  });

  await check('sending while offline reconnects automatically and delivers the message', async () => {
    const p = await sandbox({ failConnects: 1 });
    const w = p.locator('agent-widget');
    await w.locator('.aw-banner', { hasText: 'Can’t reach the assistant' }).waitFor();
    await w.getByRole('textbox').fill('Compare copays');
    await w.getByRole('textbox').press('Enter');
    await w.locator('.aw-bot-text li', { hasText: 'Specialist (dermatology)' }).waitFor();
    assert.equal(await w.locator('.aw-banner').isHidden(), true);
    assert.equal(await w.locator('.aw-user-status.is-failed').count(), 0);
    assert.deepEqual(await p.evaluate(() => window.__unhandled), []);
    await p.close();
  });

  await check('a member switch during a slow connect cannot leak the old conversation', async () => {
    const p = await sandbox({ connectDelayMs: 400 });
    const w = p.locator('agent-widget');
    await p.evaluate(() => {
      const widget = window.__widget;
      widget.setContext({ member: { ref: 'mbr_2c91', displayName: 'Jordan Lee', planName: 'Harbor PPO', idLast4: '1307', status: 'Active' } });
      widget.setContext({ member: { ref: 'mbr_7f3a', displayName: 'Alex Morgan', planName: 'Harbor HMO', idLast4: '4821', status: 'Active' } });
      void widget.sendMessage('Is a skin exam covered?');
    });
    await w.locator('.aw-card').getByText('Covered when medically necessary').waitFor();
    await p.waitForTimeout(1200);
    assert.equal(await w.locator('.aw-user').count(), 1);
    assert.equal(await w.locator('.aw-card').count(), 1, 'exactly one answer, from the live conversation');
    assert.match(await w.locator('.aw-context-name').textContent(), /Alex Morgan/);
    assert.deepEqual(await p.evaluate(() => window.__unhandled), []);
    await p.close();
  });

  await check('card renderer: ShowCard inputs are scoped, disabled cards ignore selectAction', async () => {
    const p = await sandbox({});
    const result = await p.evaluate(() => {
      const calls = [];
      const renderer = new AgentWidget.LiteCardRenderer();
      const card = {
        type: 'AdaptiveCard', version: '1.5',
        selectAction: { type: 'Action.Submit', data: { from: 'select' } },
        body: [{ type: 'Input.Text', id: 'outer', value: 'x' }],
        actions: [
          { type: 'Action.Submit', title: 'Go', data: { from: 'outer' } },
          { type: 'Action.ShowCard', title: 'More', card: { type: 'AdaptiveCard', body: [{ type: 'Input.Text', id: 'inner', isRequired: true }], actions: [{ type: 'Action.Submit', title: 'Inner go' }] } },
        ],
      };
      const rendered = renderer.render(card, { markdown: (t) => t, onAction: (a) => calls.push(a), idPrefix: 't', locale: 'en-US', strings: { required: 'Required' } });
      document.body.append(rendered.element);
      const buttons = [...rendered.element.querySelectorAll('button')];
      buttons.find((b) => b.textContent === 'Go').click(); // inner required field is hidden: must not block
      buttons.find((b) => b.textContent === 'More').click();
      buttons.find((b) => b.textContent === 'Inner go').click(); // inner required empty: blocked
      const innerBlocked = calls.length === 1;
      rendered.element.querySelector('#' + CSS.escape(rendered.element.querySelector('.ac-showcard input').id)).value = 'filled';
      buttons.find((b) => b.textContent === 'Inner go').click();
      const innerData = calls[1]?.data;
      rendered.setDisabled(true);
      rendered.element.click();
      return { first: calls[0]?.data, innerBlocked, innerData, total: calls.length };
    });
    assert.deepEqual(result.first, { from: 'outer', outer: 'x' }, 'outer submit sends only its own inputs');
    assert.equal(result.innerBlocked, true);
    assert.deepEqual(result.innerData, { outer: 'x', inner: 'filled' }, 'inner submit includes ancestor inputs');
    assert.equal(result.total, 2, 'disabled card ignores selectAction');
    await p.close();
  });

  await check('launcher mode on a phone: opens, fills the screen, Escape closes', async () => {
    const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
    phone.on('pageerror', (e) => errors.push(`phone: ${e.message}`));
    await phone.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await phone.goto(`http://localhost:${PORT}/demo/`);
    const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `page scrolls sideways by ${overflow}px`);
    await phone.evaluate(() => {
      const w = document.createElement('agent-widget');
      w.id = 'launcher';
      w.setAttribute('agent-id', 'care-assistant');
      w.setAttribute('mode', 'launcher');
      w.setAttribute('environment', 'demo');
      document.body.append(w);
      w.init({ transport: () => new AgentWidgetMock.MockRelayTransport(), context: { member: { ref: 'mbr_7f3a', displayName: 'Alex Morgan', planName: 'Harbor HMO', idLast4: '4821', status: 'Active' } } });
    });
    const launcher = phone.locator('#launcher');
    await launcher.getByRole('button', { name: 'Open care assistant' }).click();
    const box = await launcher.locator('.aw-panel').boundingBox();
    assert.ok(box && box.width >= 389 && box.height >= 840, 'full-screen panel on phones');
    await launcher.getByRole('textbox').fill('Is a skin exam covered?');
    await launcher.getByRole('textbox').press('Enter');
    await launcher.locator('.aw-card').getByText('Covered when medically necessary').waitFor();
    await phone.waitForTimeout(300);
    await phone.screenshot({ path: `${OUT}/phone-launcher.png` });
    await phone.keyboard.press('Escape');
    await launcher.getByRole('button', { name: 'Open care assistant' }).waitFor();
    await phone.close();
  });

  await check('demo page renders in dark mode', async () => {
    const dark = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: 'dark' });
    await dark.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await dark.goto(`http://localhost:${PORT}/demo/`);
    await dark.locator('agent-widget').locator('.aw-card').getByText('Covered when medically necessary').waitFor();
    await dark.waitForTimeout(400);
    await dark.screenshot({ path: `${OUT}/demo-dark.png` });
    await dark.close();
  });

  await page.screenshot({ path: `${OUT}/demo-desktop.png` });
  assert.deepEqual(errors, [], `console/page errors:\n${errors.join('\n')}`);
  console.log(`\n${results.length} e2e checks passed. Screenshots in ${OUT}/`);
} catch (err) {
  console.error(`\n✗ failed at: ${step}\n`, err);
  if (errors.length) console.error('page errors:', errors);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
