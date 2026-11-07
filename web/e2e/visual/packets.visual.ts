/** Packet analysis (NET-188) beyond the route sweep, which covers the first visit in every mode:
 * a search that is still working, its answer in every theme and width, a /tools/tshark link
 * landing on the page, and one packet's drawer on a desktop and a phone. */
import { test, expect, type Page } from '@playwright/test';
import {
	expectNoConsoleErrors, expectReached, heldCount, releaseHeld, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole,
} from './harness.ts';
import { CDN_NAME, ROWS, SEARCH_QUERY } from './fixtures/packets.ts';

const RESULTS = `/packets?${SEARCH_QUERY}`;
const kpi = (page: Page, label: string) => page.locator('main .kpi').filter({ has: page.locator('.kpi-top', { hasText: new RegExp(`^${label}$`) }) });

async function openResults(page: Page): Promise<void> {
	await setMode('populated');
	const apiIdle = watchApi(page);
	await stubUpstreams(page, 'populated');
	await page.setViewportSize(VIEWPORTS[0]);
	await page.goto(RESULTS);
	await expectReached(page, '/packets', 'Packet analysis');
	await apiIdle();
	await expect(page.getByRole('table', { name: 'Packets' }).getByRole('row')).toHaveCount(ROWS.length + 1);
}

test.describe('Packet analysis', () => {
	test('the first visit writes the filter and lists the capture files', async ({ page }) => {
		await setMode('populated');
		const apiIdle = watchApi(page);
		await stubUpstreams(page, 'populated');
		await page.setViewportSize(VIEWPORTS[1]);
		await page.goto('/packets');
		await expectReached(page, '/packets', 'Packet analysis');
		await apiIdle();
		await expect(page.getByText(/NetTap will read/)).toContainText('capture file');
		await expect(page.getByRole('table', { name: 'Capture files' }).getByText('Being written')).toBeVisible();
		await page.getByRole('button', { name: 'Name lookups', exact: true }).click();
		await expect(page.locator('main code.filter')).toHaveText('dns && dns.flags.response == 0');
	});

	test('the old TShark page lands on Packet analysis', async ({ page }) => {
		await setMode('empty');
		await page.goto('/tools/tshark?filter=dns&auto=1');
		await expectReached(page, '/packets', 'Packet analysis');
		await expect(page.getByText(/This link's search couldn't be read/)).toHaveCount(0);
	});

	test('a search shows it is working until the daemon answers', async ({ page }) => {
		await setMode('slow');
		await stubUpstreams(page, 'slow');
		await page.setViewportSize(VIEWPORTS[1]);
		await page.goto(RESULTS);
		await expectReached(page, '/packets', 'Packet analysis');
		await expect.poll(heldCount, { message: 'the daemon is holding the search' }).toBeGreaterThan(0);
		await expect(page.getByText(/Searching… \d+ s so far/)).toBeVisible();
		await expect(kpi(page, 'Packets')).toHaveCount(0);
		const apiIdle = watchApi(page);
		await releaseHeld();
		await setMode('populated');
		await apiIdle();
		await expect(kpi(page, 'Packets')).toContainText('All of them');
	});

	test('a search’s answer fits every theme and width', async ({ page }, testInfo) => {
		const errors = watchConsole(page);
		await openResults(page);
		await expect(kpi(page, 'Packets')).toContainText(String(ROWS.length));
		await expect(page.getByRole('table', { name: 'Packets' })).toContainText(CDN_NAME);
		await expect(page.getByRole('heading', { name: 'The conversation over time' })).toBeVisible();
		await sweep(page, testInfo, { route: '/packets', mode: 'populated' });
		expectNoConsoleErrors(errors, { route: '/packets', mode: 'populated' });
	});

	test('a packet’s drawer on a desktop and a phone', async ({ page }, testInfo) => {
		const errors = watchConsole(page);
		await openResults(page);
		await page.getByRole('button', { name: `Open packet ${ROWS[0].n}` }).click();
		const drawer = page.getByRole('complementary', { name: `Packet 1 of ${ROWS.length}` });
		// Only the last layer starts open
		await drawer.getByText(/^Internet Protocol Version 4/).click();
		await expect(drawer.getByText('Destination Address: 203.0.113.45')).toBeVisible();
		await drawer.getByRole('button', { name: /Destination Address/ }).click();
		await expect(drawer.locator('.hex mark').first()).toBeVisible();
		await sweep(page, testInfo, { route: '/packets', mode: 'populated' }, { variants: ['ember'], viewports: [VIEWPORTS[1], VIEWPORTS[2]] });
		expectNoConsoleErrors(errors, { route: '/packets', mode: 'populated' });
	});
});
