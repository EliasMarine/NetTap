/**
 * Live bandwidth is opt-in (NET-205): the switch in Settings › Capture, and a device page's card
 * while the setting is off (a link to the switch, no polling). Chart gaps: a missing slot's tooltip
 * carries the daemon's reason, wrapped inside the card at phone width.
 */
import { expect, test } from '@playwright/test';
import type { LiveBandwidthSupported } from '../../src/lib/api/live-bandwidth.ts';
import { LIVE_BANDWIDTH_OFF, LIVE_BANDWIDTH_ROUTES } from './fixtures/live-bandwidth.ts';
import { expectNoConsoleErrors, expectReached, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const DEVICE = '/devices/mac/02:00:5e:10:00:20';

test.beforeEach(async ({ page }) => {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.setViewportSize(VIEWPORTS[0]);
});

test('/settings?tab=capture populated: the Live bandwidth switch', async ({ page }, testInfo) => {
	const ctx = { route: '/settings', mode: 'populated' } as const;
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	await page.goto('/settings?tab=capture');
	await expectReached(page, '/settings', 'Settings');
	await apiIdle();
	await expect(page.getByRole('switch', { name: 'Live bandwidth on device pages' })).toBeChecked();
	await expect(page.getByText('On — measures while a device page is open')).toBeVisible();
	await sweep(page, testInfo, ctx);
	expectNoConsoleErrors(errors, ctx);
});

test(`${DEVICE} with live bandwidth off`, async ({ page }, testInfo) => {
	const ctx = { route: DEVICE, mode: 'populated' } as const;
	let asked = 0;
	await page.route(
		(url) => url.pathname === '/api/live-bandwidth',
		(r) => {
			asked++;
			return r.fulfill({ json: LIVE_BANDWIDTH_OFF });
		},
	);
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	await page.goto(DEVICE);
	await expectReached(page, DEVICE, 'laptop-01.example.com');
	await apiIdle();
	await expect(page.getByRole('heading', { name: 'Live bandwidth is off' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Open Settings › Capture' })).toHaveAttribute('href', '/settings?tab=capture');
	await sweep(page, testInfo, ctx);
	// one answer, then no polling (the sweep's resizes and theme changes take far longer than 2 s)
	expect(asked).toBe(1);
	expectNoConsoleErrors(errors, ctx);
});

test(`${DEVICE} at 390 px: a long reason in a missing slot's tooltip wraps inside the card`, async ({ page }) => {
	const ctx = { route: DEVICE, mode: 'populated' } as const;
	// the longest kind of reason: a tc error is unbounded
	const LONG = `Couldn't read the counters: ${'tc filter show dev enp4s0 ingress timed out after 1.0 s '.repeat(2).trim()}`;
	const populated = LIVE_BANDWIDTH_ROUTES.find((r) => r.path === '/api/live-bandwidth')!.populated as LiveBandwidthSupported;
	const reply = { ...populated, samples: populated.samples.map((s, i) => (i < 10 ? { ...s, down_bps: null, up_bps: null, reason: LONG } : s)) };
	await page.route(
		(url) => url.pathname === '/api/live-bandwidth',
		(r) => r.fulfill({ json: reply }),
	);
	const errors = watchConsole(page);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto(DEVICE);
	await expectReached(page, DEVICE, 'laptop-01.example.com');
	const chart = page.getByRole('group', { name: /^Download and upload over the last 5 minutes/ });
	await chart.focus();
	await page.keyboard.press('Home'); // slot 0 is one of the missing ones
	const tip = chart.locator('rect.tip-bg');
	await expect(tip).toBeVisible();
	expect(await chart.locator('.tip-tx tspan').count()).toBeGreaterThan(1);
	const box = (await tip.boundingBox())!;
	const card = (await chart.locator('xpath=ancestor::article[contains(@class, "card")][1]').boundingBox())!;
	expect(box.x).toBeGreaterThanOrEqual(card.x);
	expect(box.x + box.width).toBeLessThanOrEqual(card.x + card.width);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
	expectNoConsoleErrors(errors, ctx);
});
