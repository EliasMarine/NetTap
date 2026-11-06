/** NET-180: Devices By type in mirror mode. In every band of a type group's grid, each card's
 * stats start at the same height (its first label within 1 px of its neighbours'), whatever wraps
 * above or inside them: at 1440 px and either side of the grid's 3-to-2 (1100 px) and 2-to-1
 * (760 px) column breakpoints, in every theme. Then the List layout: one sortable table per group,
 * no horizontal page scroll down to 390 px, and screenshots of both layouts. */
import { test, expect, type Page } from '@playwright/test';
import { VARIANTS, expectReached, setMode, setVariant, settle, stubUpstreams, watchApi } from './harness.ts';
import { BY_TYPE_LAYOUT } from './fixtures/devices.ts';

/** The grid's column breakpoints are on the app container (system.css: `@container app`). */
const BREAKPOINTS = { twoPerBand: 1100, onePerBand: 760 };

/** 1440 px, then 12 px of app width either side of each breakpoint, with the cards a full band holds there. */
async function cardWidths(page: Page): Promise<{ width: number; perBand: number }[]> {
	const inset = 1440 - (await page.locator('.app').evaluate((el) => el.getBoundingClientRect().width));
	const at = (appWidth: number) => Math.round(appWidth + inset);
	return [
		{ width: 1440, perBand: 3 },
		{ width: at(BREAKPOINTS.twoPerBand + 12), perBand: 3 },
		{ width: at(BREAKPOINTS.twoPerBand - 12), perBand: 2 },
		{ width: at(BREAKPOINTS.onePerBand + 12), perBand: 2 },
		{ width: at(BREAKPOINTS.onePerBand - 12), perBand: 1 },
	];
}

/** The fixture's capture mode is bridge; this serves mirror mode, and the registry and list with the band. */
async function open(page: Page): Promise<void> {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.route((url) => url.pathname === '/api/capture/mode', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.mode }));
	await page.route((url) => url.pathname === '/api/devices/registry', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.registry }));
	await page.route((url) => url.pathname === '/api/devices', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.list }));
	await page.setViewportSize({ width: 1440, height: 900 });
	const apiIdle = watchApi(page);
	await page.goto('/devices');
	await expectReached(page, '/devices', 'Devices');
	await apiIdle();
	await expect(page.getByRole('tab', { name: 'By type' })).toHaveAttribute('aria-selected', 'true');
	await expect(page.locator('main .dev-card').filter({ hasText: 'DESKTOP-1H4Q4HV' })).toContainText('Maker unknown');
}

/** Each band of cards (cards sharing a top) with each card's first stats label top. Runs in the page. */
function bands() {
	return [...document.querySelectorAll('main .type-group .grid')].flatMap((grid) => {
		const byTop = new Map<number, { name: string; label: number }[]>();
		for (const card of grid.querySelectorAll(':scope > .dev-card')) {
			const top = Math.round(card.getBoundingClientRect().top);
			const name = card.querySelector('.dev-name')?.textContent ?? '?';
			const label = card.querySelector('.meta-k')!.getBoundingClientRect().top;
			byTop.set(top, [...(byTop.get(top) ?? []), { name, label }]);
		}
		return [...byTop.values()];
	});
}

/** How tall a card's Connections value is, in lines of its own text. Runs in the page. */
function connectionLines(name: string) {
	const card = [...document.querySelectorAll('main .dev-card')].find((c) => c.querySelector('.dev-name')?.textContent === name)!;
	const value = [...card.querySelectorAll('.meta-k')].find((k) => k.textContent === 'Connections')!.nextElementSibling!;
	return value.getBoundingClientRect().height / parseFloat(getComputedStyle(value).lineHeight);
}

test.describe('Devices By type layout (NET-180)', () => {
	for (const variant of VARIANTS) {
		test(`every card's stats line up with its neighbours' in ${variant}`, async ({ page }, testInfo) => {
			await open(page);
			await setVariant(page, variant);
			for (const { width, perBand } of await cardWidths(page)) {
				await page.setViewportSize({ width, height: 900 });
				await settle(page);
				const found = await page.evaluate(bands);
				// the right side of the breakpoint, and the stress case really happens: a count that wraps beside one that doesn't
				expect(Math.max(...found.map((band) => band.length)), `${width} px: cards in a full band`).toBe(perBand);
				if (perBand > 1) {
					expect(await page.evaluate(connectionLines, 'build-server.example.com'), `${width} px: the long count wraps`).toBeGreaterThan(1.5);
				}
				const misaligned = found
					.filter((band) => Math.max(...band.map((c) => c.label)) - Math.min(...band.map((c) => c.label)) > 1)
					.map((band) => band.map((c) => `${c.name} ${c.label.toFixed(1)}`).join(' / '));
				expect.soft(misaligned, `${variant} @ ${width} px: stats labels out of line`).toEqual([]);
				if (width === 1440) await page.screenshot({ path: testInfo.outputPath(`cards-${variant}-${width}.png`), fullPage: true });
			}
		});
	}

	test('List shows one sortable table per group and fits the page down to 390 px', async ({ page }, testInfo) => {
		await open(page);
		await page.getByRole('group', { name: 'Layout' }).getByRole('button', { name: 'List' }).click();
		const groups = await page.locator('main .type-group').count();
		await expect(page.locator('main .type-group table')).toHaveCount(groups);
		await expect(page.locator('main .dev-card')).toHaveCount(0);
		const computers = page.getByRole('table', { name: 'Computers, as a list' });
		await expect(computers.getByRole('columnheader', { name: 'Last seen' })).toHaveAttribute('aria-sort', 'descending');
		await expect(computers.getByRole('row').nth(1)).toContainText('DESKTOP-1H4Q4HV');
		for (const variant of VARIANTS) {
			await setVariant(page, variant);
			for (const width of [1440, 390]) {
				await page.setViewportSize({ width, height: 900 });
				await settle(page);
				const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
				expect.soft(scrollWidth, `horizontal scroll, ${variant} @ ${width}`).toBeLessThanOrEqual(width);
				await page.screenshot({ path: testInfo.outputPath(`list-${variant}-${width}.png`), fullPage: true });
			}
		}
	});
});
