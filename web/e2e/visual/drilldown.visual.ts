/** The address and domain pages (NET-160) in the states the route sweep doesn't show on its own:
 * loading while the daemon works, then each figure's honest wording once it answers. The route
 * sweep (routes.ts) covers their empty, error and populated looks in every theme and width. */
import { test, expect, type Page } from '@playwright/test';
import { expectReached, heldCount, releaseHeld, setMode, stubUpstreams, watchApi } from './harness.ts';

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
