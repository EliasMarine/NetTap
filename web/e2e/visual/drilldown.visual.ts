/** The address and domain pages (NET-160) in the states the route sweep doesn't show on its own:
 * loading while the daemon works, then each figure's honest wording once it answers. The route
 * sweep (routes.ts) covers their empty, error and populated looks in every theme and width. */
import { test, expect, type Page } from '@playwright/test';
// OLD CODE: import { expectReached, heldCount, releaseHeld, setMode, stubUpstreams, watchApi } from './harness.ts'; (slice 2b-2)
import { expectNoConsoleErrors, expectReached, heldCount, releaseHeld, setMode, stubUpstreams, sweep, watchApi, watchConsole } from './harness.ts';

// By the card's own label: hasText alone is a case-insensitive substring, so "Connections" would also match "… connections measured"
const kpi = (page: Page, label: string) => page.locator('main .kpi').filter({ has: page.locator('.kpi-top', { hasText: new RegExp(`^${label}$`) }) });

async function openSlow(page: Page, path: string, marker: string): Promise<void> {
	await setMode('slow');
	await stubUpstreams(page, 'slow');
	await page.setViewportSize({ width: 1440, height: 900 });
	await page.goto(path);
	await expectReached(page, path, marker);
	await expect.poll(heldCount, { message: 'the daemon is holding the page’s requests' }).toBeGreaterThan(0);
}

async function answer(page: Page): Promise<void> {
	const apiIdle = watchApi(page);
	await releaseHeld();
	await setMode('populated');
	await apiIdle();
}

test.describe('drill-down pages', () => {
	test('an address shows loading, never zeros, then partial and complete figures', async ({ page }) => {
		await openSlow(page, '/address/198.51.100.10', '198.51.100.10');
		await expect(page.locator('main [aria-busy="true"]').first()).toBeVisible();
		await expect(kpi(page, 'Connections')).toContainText('—');
		await answer(page);
		await expect(kpi(page, 'Connections')).toContainText('1,980');
		await expect(kpi(page, 'Data to it')).toContainText('at least');
		await expect(kpi(page, 'Data to it')).toContainText('1,970 of 1,980 connections measured');
		await expect(page.getByText('Not on a threat list')).toBeVisible();
	});

	test('an address with no byte counts says Not measured and withholds what it could not count', async ({ page }) => {
		await openSlow(page, '/address/192.0.2.80', '192.0.2.80');
		await answer(page);
		await expect(kpi(page, 'Data to it')).toContainText('Not measured');
		await expect(kpi(page, 'Devices that talked to it')).toContainText('too many to count');
		await expect(page.getByText(/On a threat list/)).toBeVisible();
		await expect(page.getByText('No name (SNI)')).toBeVisible();
	});

	test('a domain shows loading, then its tagged alerts with their coverage', async ({ page }) => {
		await openSlow(page, '/domain/stream.example.net', 'stream.example.net');
		await expect(page.locator('main [aria-busy="true"]').first()).toBeVisible();
		await answer(page);
		await expect(kpi(page, 'Lookups')).toContainText('420');
		await expect(page.getByText('Only 12 of 57 alerts in this window carry a host name.')).toBeVisible();
	});

	test('a domain whose alerts carry no host names says Not recorded', async ({ page }) => {
		await openSlow(page, '/domain/quiet.example.org', 'quiet.example.org');
		await answer(page);
		await expect(page.locator('main .card').filter({ hasText: 'Alerts tagged with this name' })).toContainText('Not recorded');
		await expect(kpi(page, 'Addresses it resolved to')).toContainText('too many to count');
	});
});

// NET-160 slice 2b-2: a raw Suricata category's page
test.describe('Suricata category page', () => {
	test('a name with "/", "&" and "%" reaches the daemon encoded once and heads the page', async ({ page }) => {
		const name = 'A/B & C 50%';
		const path = `/alerts/suricata/${encodeURIComponent(name)}`;
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		const apiIdle = watchApi(page);
		const figures = page.waitForRequest((r) => new URL(r.url()).pathname.startsWith('/api/alerts/suricata/'));
		await page.goto(path);
		const request = await figures;
		expect(new URL(request.url()).pathname).toBe('/api/alerts/suricata/A%2FB%20%26%20C%2050%25');
		// the web server routed it to the catch-all proxy and the daemon fixture answered
		expect((await request.response())?.status()).toBe(200);
		await expectReached(page, path, name);
		await apiIdle();
		await expect(page.locator('main h1.page-title')).toHaveText(name);
		await expect(kpi(page, 'Alerts')).toContainText('1,240');
	});

	test('the populated page also fits 1024 and 768 in every theme (the route sweep covers 1920, 1440 and 390)', async ({ page }, testInfo) => {
		const path = '/alerts/suricata/Misc%20activity';
		await setMode('populated');
		const errors = watchConsole(page);
		const apiIdle = watchApi(page);
		await stubUpstreams(page, 'populated');
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(path);
		await expectReached(page, path, 'Misc activity');
		await apiIdle();
		await expect(page.getByText('Highest counts among the 5,000 addresses read; the full set was too large to read.')).toBeVisible();
		await sweep(page, testInfo, { route: path, mode: 'populated' }, { viewports: [{ width: 1024, height: 768 }, { width: 768, height: 1024 }] });
		expectNoConsoleErrors(errors, { route: path, mode: 'populated' });
	});
});
