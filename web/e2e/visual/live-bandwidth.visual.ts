/**
 * Live bandwidth is opt-in (NET-205): the switch in Settings › Capture, and a device page's card
 * while the setting is off (a link to the switch, no polling).
 */
import { expect, test } from '@playwright/test';
import { LIVE_BANDWIDTH_OFF } from './fixtures/live-bandwidth.ts';
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
