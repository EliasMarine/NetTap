/**
 * NET-269: Compare periods on the MAC device page (Devices › By type opens it), for a device with
 * an IPv4 and a long IPv6 address, so the Address picker and the line naming the address show.
 */
import { expect, test } from '@playwright/test';
import { expectNoConsoleErrors, expectReached, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const MAC = '02:00:5e:10:00:20';
const DEVICE = `/devices/mac/${MAC}`;
const V6 = '2001:db8:4f2a:1c00:9d3e:21ff:fe5e:3532';

test.beforeEach(async ({ page }) => {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.setViewportSize(VIEWPORTS[0]);
});

test(`${DEVICE} with Compare periods open`, async ({ page }, testInfo) => {
	const ctx = { route: DEVICE, mode: 'populated' } as const;
	// the fixture device, with an IPv6 that sorts before its IPv4 (as the registry sorts them)
	await page.route(
		(url) => decodeURIComponent(url.pathname) === `/api/devices/registry/${MAC}`,
		async (r) => {
			const body = await (await r.fetch()).json();
			return r.fulfill({ json: { ...body, device: { ...body.device, ips: [V6, ...body.device.ips] } } });
		},
	);
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	await page.goto(DEVICE);
	await expectReached(page, DEVICE, 'laptop-01.example.com');
	await apiIdle();
	await expect(page.getByRole('link', { name: 'DHCP history' })).toHaveAttribute('href', `/tools/dhcp-timeline?mac=${encodeURIComponent(MAC)}`);
	await page.getByRole('button', { name: 'Compare periods' }).click();
	const address = page.getByLabel('Address');
	await expect(address).toBeFocused();
	await expect(address).toHaveValue('192.168.1.20');
	await expect(page.getByText('Compares 192.168.1.20 in both periods.', { exact: false })).toBeVisible();
	await sweep(page, testInfo, ctx);
	expectNoConsoleErrors(errors, ctx);
});
