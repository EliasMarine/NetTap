/** NET-373: a refused "Download filtered" opened its raw JSON in a new tab, away from the form. In a real
 * browser (opener, postMessage, pop-up close and a native download): the reason shows beside the dates,
 * the tab closes, the filter and dates stay, and a window the daemon accepts downloads once. */
import { readFile } from 'node:fs/promises';
import { test, expect } from '@playwright/test';
import { expectNoConsoleErrors, expectReached, setMode, stubUpstreams, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const EMPTY = 'No capture file holds packets from this window.';
const FILTER = 'ip.addr == 192.0.2.123';

test('PCAP Search: a refused download says why beside its dates, and an accepted one downloads', async ({ page, context }, testInfo) => {
	test.skip(testInfo.project.name === 'reduced-motion', 'covered by the app project');
	await setMode('empty');
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	await stubUpstreams(page, 'empty');
	await page.setViewportSize(VIEWPORTS[2]); // a phone: the message must not widen the page
	await page.goto('/pcap');
	await expectReached(page, '/pcap', 'PCAP search');
	await apiIdle();

	const filter = page.getByLabel('Wireshark display filter');
	const from = page.getByLabel('Download from');
	const to = page.getByLabel('to', { exact: true });
	const button = page.getByRole('button', { name: /Download filtered/ });
	await filter.fill(FILTER);
	await expect(button).toBeEnabled();
	await from.fill('2001-01-01T00:00:00');
	await to.fill('2001-01-01T00:01:00');

	const popupOpened = page.waitForEvent('popup');
	await button.click();
	const popup = await popupOpened;
	await expect(page.locator('#pcap-download-error')).toHaveText(EMPTY);
	await expect.poll(() => popup.isClosed()).toBe(true);
	await expect(filter).toHaveValue(FILTER);
	await expect(from).toHaveValue(/^2001-01-01T00:00(:00)?$/);
	await expect(to).toHaveValue(/^2001-01-01T00:01(:00)?$/);
	const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
	expect(overflow, 'the message widens the page').toBeLessThanOrEqual(0);

	// A window the daemon accepts: one native download (Chromium may report a pop-up's first-navigation
	// attachment on the opener, so listen on the context)
	await from.fill('2026-11-12T17:00:00');
	await to.fill('2026-11-12T17:00:20');
	const downloads: string[] = [];
	context.on('download', (d) => downloads.push(d.suggestedFilename()));
	const downloaded = context.waitForEvent('download');
	await button.click();
	const download = await downloaded;
	expect(download.suggestedFilename()).toBe('nettap_filtered.pcap');
	const bytes = await readFile((await download.path())!);
	expect(bytes.toString('hex')).toBe('d4c3b2a1020004000000000000000000ffff000001000000');
	await expect(page.locator('#pcap-download-error')).toHaveCount(0);
	expect(downloads).toHaveLength(1);
	expectNoConsoleErrors(errors, { route: '/pcap', mode: 'empty' });
});
