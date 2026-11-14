/** Packet analysis (NET-188) beyond the route sweep, which covers the first visit in every mode:
 * a search that is still working, its answer in every theme and width, a /tools/tshark link
 * landing on the page, and one packet's drawer on a desktop and a phone. NET-276: a search opened
 * from outside NetTap (any page.goto here) waits for Run; one started inside NetTap runs at once. */
import { test, expect, type Page } from '@playwright/test';
import {
	expectNoConsoleErrors, expectReached, heldCount, releaseHeld, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole,
} from './harness.ts';
import { CDN_NAME, ROWS, SEARCH_QUERY } from './fixtures/packets.ts';
import { APP_ROUTES } from './routes.ts';

const RESULTS = `/packets?${SEARCH_QUERY}`;
/** The route sweep's moment: a 5-minute window, so it offers "Search packets in this window". */
const MOMENT = APP_ROUTES.find((r) => r.path.startsWith('/moment?'))!.path;
const kpi = (page: Page, label: string) => page.locator('main .kpi').filter({ has: page.locator('.kpi-top', { hasText: new RegExp(`^${label}$`) }) });
const runButton = (page: Page) => page.getByRole('button', { name: 'Run the search' });
const packetRows = (page: Page) => page.getByRole('table', { name: 'Packets' }).getByRole('row');

/** The body of every packet search the page asks for, in order. */
function watchSearches(page: Page): unknown[] {
	const bodies: unknown[] = [];
	page.on('request', (r) => {
		if (new URL(r.url()).pathname === '/api/packets/search') bodies.push(r.postDataJSON());
	});
	return bodies;
}

async function openResults(page: Page): Promise<void> {
	await setMode('populated');
	const apiIdle = watchApi(page);
	await stubUpstreams(page, 'populated');
	await page.setViewportSize(VIEWPORTS[0]);
	await page.goto(RESULTS);
	await expectReached(page, '/packets', 'Packet analysis');
	await apiIdle();
	// NET-276: a full load waits for Run
	const searched = watchApi(page);
	await runButton(page).click();
	await searched();
	await expect(packetRows(page)).toHaveCount(ROWS.length + 1);
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
		const searches = watchSearches(page);
		// The captures request means the page has started and run its loader
		const loaded = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/packets/captures');
		await page.goto(RESULTS);
		await expectReached(page, '/packets', 'Packet analysis');
		await loaded;
		await expect(runButton(page)).toBeVisible();
		expect(searches).toHaveLength(0);
		await runButton(page).click();
		await expect.poll(() => searches.length).toBe(1);
		await expect.poll(heldCount, { message: 'the daemon is holding the search' }).toBeGreaterThan(0);
		await expect(page.getByText(/Searching… \d+ s so far/)).toBeVisible();
		await expect(kpi(page, 'Packets')).toHaveCount(0);
		const apiIdle = watchApi(page);
		await releaseHeld();
		await setMode('populated');
		await apiIdle();
		await expect(kpi(page, 'Packets')).toContainText('All of them');
	});

	test('a search opened from outside NetTap waits for Run, and an edited one runs', async ({ page }) => {
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		await page.setViewportSize(VIEWPORTS[1]);
		const searches = watchSearches(page);
		const apiIdle = watchApi(page);
		await page.goto(RESULTS);
		await expectReached(page, '/packets', 'Packet analysis');
		await apiIdle();
		await expect(page.getByRole('heading', { name: "This search hasn't run yet" })).toBeVisible();
		await expect(page.locator('main code.filter')).toHaveText(new URLSearchParams(SEARCH_QUERY).get('filter')!);
		expect(searches).toHaveLength(0);

		await page.getByRole('button', { name: 'Edit filter' }).click();
		await page.getByRole('combobox', { name: 'Display filter' }).fill('dns');
		await page.getByRole('button', { name: 'Find packets' }).click();
		await expect(page).toHaveURL(/[?&]filter=dns(&|$)/);
		await expect(packetRows(page)).toHaveCount(ROWS.length + 1);
		expect(searches).toEqual([expect.objectContaining({ filter: 'dns' })]);
		await expect(runButton(page)).toHaveCount(0);
	});

	test('a search started inside NetTap runs straight away, and so do Back and Forward', async ({ page }) => {
		await setMode('populated');
		await stubUpstreams(page, 'populated');
		await page.setViewportSize(VIEWPORTS[0]);
		const searches = watchSearches(page);
		const apiIdle = watchApi(page);
		await page.goto(MOMENT);
		await expectReached(page, '/moment', 'What your network was doing');
		await apiIdle();

		await page.getByRole('link', { name: 'Search packets in this window' }).click();
		await expect(page).toHaveURL(/\/packets\?/);
		await expectReached(page, '/packets', 'Packet analysis');
		await expect(packetRows(page)).toHaveCount(ROWS.length + 1);
		await expect(runButton(page)).toHaveCount(0);
		expect(searches).toHaveLength(1);

		// Another search from inside the page: the packet's whole conversation
		await page.getByRole('button', { name: `Open packet ${ROWS[0].n}` }).click();
		await page.getByRole('link', { name: 'Show its whole conversation' }).click();
		await expect.poll(() => searches.length).toBe(2);
		expect(searches[1]).not.toEqual(searches[0]);
		await expect(packetRows(page)).toHaveCount(ROWS.length + 1);

		await page.goBack();
		await expect.poll(() => searches.length).toBe(3);
		expect(searches[2]).toEqual(searches[0]);
		await page.goForward();
		await expect.poll(() => searches.length).toBe(4);
		expect(searches[3]).toEqual(searches[1]);
		await expect(runButton(page)).toHaveCount(0);
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
