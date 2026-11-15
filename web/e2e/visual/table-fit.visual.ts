/**
 * NET-284 / NET-285: at 1440 px the DHCP timeline's and the Changelog's tables fit their cards,
 * so no column is clipped at the card's right edge (the system's `.tbl-wrap` scrolls instead,
 * which overlay scrollbars hide). NET-284 also: the packets link and the hint after it are
 * separated.
 */
import { expect, test, type Page } from '@playwright/test';
import { expectReached, setMode, stubUpstreams, watchApi } from './harness.ts';

const ROUTES = [
	{ path: '/tools/dhcp-timeline?mac=02:00:5e:00:53:38', marker: 'DHCP lease timeline', table: 'DHCP transactions for' },
	{ path: '/changelog', marker: 'Changelog', table: 'Changelog events' },
] as const;

/** The table's scroll container and card, and the last header cell's right edge. Runs in the page. */
function fit(label: string) {
	const table = [...document.querySelectorAll('main table')].find((t) => t.getAttribute('aria-label')?.startsWith(label))!;
	const wrap = table.closest('.tbl-wrap')!;
	const heads = [...table.querySelectorAll('th')];
	return {
		overflow: wrap.scrollWidth - wrap.clientWidth,
		lastHeadRight: Math.round(heads[heads.length - 1].getBoundingClientRect().right),
		cardRight: Math.round(table.closest('.card')!.getBoundingClientRect().right),
	};
}

async function open(page: Page, route: (typeof ROUTES)[number]): Promise<void> {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.setViewportSize({ width: 1440, height: 900 });
	const apiIdle = watchApi(page);
	await page.goto(route.path);
	await expectReached(page, route.path, route.marker);
	await apiIdle();
	await expect(page.locator('main table').first()).toBeVisible();
}

for (const route of ROUTES) {
	test(`${route.path} table fits its card at 1440 px`, async ({ page }, testInfo) => {
		await open(page, route);
		const found = await page.evaluate(fit, route.table);
		expect(found.overflow, 'the table scrolls inside its card: a column is clipped').toBeLessThanOrEqual(0);
		expect(found.lastHeadRight, "the last column's header runs past the card").toBeLessThanOrEqual(found.cardRight);
		await page.screenshot({ path: testInfo.outputPath('table-fit-1440.png'), fullPage: true });
	});
}

test('DHCP timeline: the packets link and the hint after it are separated', async ({ page }) => {
	await open(page, ROUTES[0]);
	const gaps = await page.evaluate(() =>
		[...document.querySelectorAll<HTMLAnchorElement>('main table a[aria-label^="See the captured packets"]')].map((a) => {
			// the hint's first line box: a hint that wraps has a bounding box reaching back to the cell's left edge
			const hint = a.nextElementSibling!.getClientRects()[0];
			const link = a.getBoundingClientRect();
			// on one line the hint starts after the link ends; wrapped onto the next line it starts below it
			return { text: a.parentElement!.textContent, gap: hint.top < link.bottom ? hint.left - link.right : Infinity };
		}),
	);
	expect(gaps.length).toBeGreaterThan(0);
	for (const { text, gap } of gaps) {
		expect(text, 'a space between the link and the hint').toContain('See the captured packets Shows which');
		expect(gap, 'a visible gap between the link and the hint').toBeGreaterThanOrEqual(2);
	}
});
