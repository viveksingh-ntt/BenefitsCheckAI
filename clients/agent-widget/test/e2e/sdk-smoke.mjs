// Smoke test for createSdkRenderer() with Microsoft's `adaptivecards` package.
//   npm install && npm run test:sdk
// Renders the real template catalogue through the SDK and checks the custom elements and actions.
import { chromium } from 'playwright';
import { existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import { startServer } from '../../scripts/serve.mjs';

const candidates = ['node_modules/adaptivecards/dist/adaptivecards.min.js', 'node_modules/adaptivecards/dist/adaptivecards.js'];
const umd = candidates.find((p) => existsSync(p));
if (!umd) {
  console.log('adaptivecards is not installed: run `npm install` first (it is a devDependency). Skipping.');
  process.exit(0);
}

const PORT = 5176;
const server = await startServer(PORT);
const browser = await chromium.launch();
const errors = [];
try {
  const page = await browser.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`http://localhost:${PORT}/demo/blank.html`);
  await page.addScriptTag({ url: `/${umd}` });
  await page.addScriptTag({ url: '/dist/agent-widget-sdk-renderer.iife.js' });

  const result = await page.evaluate(async () => {
    const load = async (id) => (await fetch(`/templates/${id}.json`)).json();
    const renderer = AgentWidgetSdk.createSdkRenderer(window.AdaptiveCards);
    const actions = [];
    const ctx = { markdown: (t) => t, onAction: (a) => actions.push(a), idPrefix: 's', locale: 'en-US', strings: { required: 'Required' } };
    const out = {};

    const doctors = AgentWidgetMock.expandTemplate(await load('provider-results@1'), {
      title: 'Doctors', plan: 'Harbor HMO', radius: 5, zip: '10012', selected: 'prv_19', audience: 'member', serviceRef: 'svc', notice: 'n',
      doctors: [
        { ref: 'prv_19', initials: 'NP', name: 'Dr. Nina Patel', specialty: 'Dermatologist', practice: 'SoHo Skin', services: 's', network: 'In-network', address: '210 Spring St', distanceText: '0.6 miles away' },
        { ref: 'prv_42', initials: 'DC', name: 'Dr. Daniel Chen', specialty: 'Dermatologist', practice: 'Union', services: 's', network: 'In-network', address: '30 E 14th St', distanceText: '1.3 miles away' },
      ],
    });
    const r1 = renderer.render(doctors, ctx);
    document.body.append(r1.element);
    const radios = [...r1.element.querySelectorAll('input[type=radio]')];
    out.radioCount = radios.length;
    out.preselected = radios.find((r) => r.checked)?.value;
    radios[1].click();
    [...r1.element.querySelectorAll('button')].find((b) => b.textContent.includes('Check availability')).click();
    out.execute = actions.at(-1);
    [...r1.element.querySelectorAll('button')].find((b) => b.textContent.includes('View doctor')).click();
    out.view = actions.at(-1);
    r1.setDisabled(true);
    out.disabledButtons = [...r1.element.querySelectorAll('button')].every((b) => b.disabled);

    const benefit = AgentWidgetMock.expandTemplate(await load('benefit-coverage@1'), {
      service: { name: 'Medical skin exam', category: 'Dermatology', ref: 'svc' }, plan: { name: 'Harbor HMO', year: '2026', ref: 'pln' },
      coverage: { label: 'Covered when medically necessary' }, facts: [{ title: 'Network', value: 'In-network' }], notice: 'n',
    });
    const r2 = renderer.render(benefit, ctx);
    document.body.append(r2.element);
    out.badgeText = r2.element.textContent.includes('Covered when medically necessary');

    const referral = AgentWidgetMock.expandTemplate(await load('referral-review@1'), {
      memberName: 'Alex Morgan', providerRef: 'prv_19', serviceRef: 'svc', facts: [{ title: 'Member', value: 'Alex' }], notice: 'n',
    });
    const r3 = renderer.render(referral, ctx);
    document.body.append(r3.element);
    const before = actions.length;
    [...r3.element.querySelectorAll('button')].find((b) => b.textContent.includes('Submit referral')).click();
    out.requiredToggleBlocks = actions.length === before;
    return out;
  });

  assert.equal(result.radioCount, 2, 'Org.SelectableList renders one radio per doctor');
  assert.equal(result.preselected, 'prv_19');
  assert.equal(result.execute.type, 'Action.Execute');
  assert.equal(result.execute.verb, 'appointment.availability');
  assert.equal(result.execute.data.providerRef, 'prv_42', 'selected radio is submitted');
  assert.equal(result.view.actionData.keepActive, true, 'keepActive flag reaches the widget');
  assert.equal(result.disabledButtons, true);
  assert.equal(result.badgeText, true, 'Badge (or its fallback) renders');
  assert.equal(result.requiredToggleBlocks, true, 'required attestation blocks submit');
  assert.deepEqual(errors, []);
  console.log('SDK renderer smoke test passed with', umd);
} catch (err) {
  console.error('SDK renderer smoke test FAILED:\n', err, errors);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
