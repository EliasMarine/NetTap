/** NET-180: Devices By type in mirror mode. NET-201: the owner dropped the cards, so By type is the
 * List layout only: one sortable table per group, no Layout switch, no horizontal page scroll down
 * to 390 px, and screenshots in every theme. (The cards' line-up checks are kept below as OLD CODE.)
 * NET-296: the owner dropped the By type tab, so mirror mode opens the All devices table: no tabs,
 * no horizontal page scroll down to 390 px, screenshots in every theme. */
import { test, expect, type Page } from '@playwright/test';
import { VARIANTS, expectReached, setMode, setVariant, settle, stubUpstreams, watchApi } from './harness.ts';
import { BY_TYPE_LAYOUT } from './fixtures/devices.ts';

// OLD CODE START — NET-201: the Cards layout's breakpoints
// /** The grid's column breakpoints are on the app container (system.css: `@container app`). */
// const BREAKPOINTS = { twoPerBand: 1100, onePerBand: 760 };
//
// /** 1440 px, then 12 px of app width either side of each breakpoint, with the cards a full band holds there. */
// async function cardWidths(page: Page): Promise<{ width: number; perBand: number }[]> {
// 	const inset = 1440 - (await page.locator('.app').evaluate((el) => el.getBoundingClientRect().width));
// 	const at = (appWidth: number) => Math.round(appWidth + inset);
// 	return [
// 		{ width: 1440, perBand: 3 },
// 		{ width: at(BREAKPOINTS.twoPerBand + 12), perBand: 3 },
// 		{ width: at(BREAKPOINTS.twoPerBand - 12), perBand: 2 },
// 		{ width: at(BREAKPOINTS.onePerBand + 12), perBand: 2 },
// 		{ width: at(BREAKPOINTS.onePerBand - 12), perBand: 1 },
// 	];
// }
// OLD CODE END

/** The fixture's capture mode is bridge; this serves mirror mode, and the registry and list with the band. */
// OLD CODE: async function open(page: Page): Promise<void> { (NET-318: a test serves its own list)
async function open(page: Page, list: typeof BY_TYPE_LAYOUT.list = BY_TYPE_LAYOUT.list): Promise<void> {
	await setMode('populated');
	await stubUpstreams(page, 'populated');
	await page.route((url) => url.pathname === '/api/capture/mode', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.mode }));
	await page.route((url) => url.pathname === '/api/devices/registry', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.registry }));
	// OLD CODE: await page.route((url) => url.pathname === '/api/devices', (r) => r.fulfill({ json: BY_TYPE_LAYOUT.list })); (NET-318)
	await page.route((url) => url.pathname === '/api/devices', (r) => r.fulfill({ json: list }));
	await page.setViewportSize({ width: 1440, height: 900 });
	const apiIdle = watchApi(page);
	await page.goto('/devices');
	await expectReached(page, '/devices', 'Devices');
	await apiIdle();
	// OLD CODE START — NET-296: mirror mode opened on By type
	// await expect(page.getByRole('tab', { name: 'By type' })).toHaveAttribute('aria-selected', 'true');
	// // OLD CODE: await expect(page.locator('main .dev-card').filter({ hasText: 'DESKTOP-1H4Q4HV' })).toContainText('Maker unknown'); (NET-201: rows)
	// await expect(page.locator('main .type-group tr').filter({ hasText: 'DESKTOP-1H4Q4HV' })).toContainText('Maker unknown');
	// OLD CODE END
	await expect(page.getByRole('table', { name: 'All devices' })).toBeVisible();
	await expect(page.getByRole('tab')).toHaveCount(0);
}

// OLD CODE START — NET-201: the cards' band and line helpers
// /** Each band of cards (cards sharing a top) with each card's first stats label top. Runs in the page. */
// function bands() {
// 	return [...document.querySelectorAll('main .type-group .grid')].flatMap((grid) => {
// 		const byTop = new Map<number, { name: string; label: number }[]>();
// 		for (const card of grid.querySelectorAll(':scope > .dev-card')) {
// 			const top = Math.round(card.getBoundingClientRect().top);
// 			const name = card.querySelector('.dev-name')?.textContent ?? '?';
// 			const label = card.querySelector('.meta-k')!.getBoundingClientRect().top;
// 			byTop.set(top, [...(byTop.get(top) ?? []), { name, label }]);
// 		}
// 		return [...byTop.values()];
// 	});
// }
//
// /** How tall a card's Connections value is, in lines of its own text. Runs in the page. */
// function connectionLines(name: string) {
// 	const card = [...document.querySelectorAll('main .dev-card')].find((c) => c.querySelector('.dev-name')?.textContent === name)!;
// 	const value = [...card.querySelectorAll('.meta-k')].find((k) => k.textContent === 'Connections')!.nextElementSibling!;
// 	return value.getBoundingClientRect().height / parseFloat(getComputedStyle(value).lineHeight);
// }
// OLD CODE END

// OLD CODE: test.describe('Devices By type layout (NET-180)', () => { (NET-296)
test.describe('Devices layout in mirror mode (NET-180, NET-296)', () => {
	// OLD CODE START — NET-201: no cards to line up
	// for (const variant of VARIANTS) {
	// 	test(`every card's stats line up with its neighbours' in ${variant}`, async ({ page }, testInfo) => {
	// 		await open(page);
	// 		await setVariant(page, variant);
	// 		for (const { width, perBand } of await cardWidths(page)) {
	// 			await page.setViewportSize({ width, height: 900 });
	// 			await settle(page);
	// 			const found = await page.evaluate(bands);
	// 			// the right side of the breakpoint, and the stress case really happens: a count that wraps beside one that doesn't
	// 			expect(Math.max(...found.map((band) => band.length)), `${width} px: cards in a full band`).toBe(perBand);
	// 			if (perBand > 1) {
	// 				expect(await page.evaluate(connectionLines, 'build-server.example.com'), `${width} px: the long count wraps`).toBeGreaterThan(1.5);
	// 			}
	// 			const misaligned = found
	// 				.filter((band) => Math.max(...band.map((c) => c.label)) - Math.min(...band.map((c) => c.label)) > 1)
	// 				.map((band) => band.map((c) => `${c.name} ${c.label.toFixed(1)}`).join(' / '));
	// 			expect.soft(misaligned, `${variant} @ ${width} px: stats labels out of line`).toEqual([]);
	// 			if (width === 1440) await page.screenshot({ path: testInfo.outputPath(`cards-${variant}-${width}.png`), fullPage: true });
	// 		}
	// 	});
	// }
	// OLD CODE END

	// OLD CODE START — NET-296: By type's one-table-per-group layout is gone
	// test('List shows one sortable table per group and fits the page down to 390 px', async ({ page }, testInfo) => {
	// 	await open(page);
	// 	// OLD CODE: await page.getByRole('group', { name: 'Layout' }).getByRole('button', { name: 'List' }).click(); (NET-201: the list is all there is)
	// 	await expect(page.getByRole('group', { name: 'Layout' })).toHaveCount(0);
	// 	const groups = await page.locator('main .type-group').count();
	// 	await expect(page.locator('main .type-group table')).toHaveCount(groups);
	// 	await expect(page.locator('main .dev-card')).toHaveCount(0);
	// 	const computers = page.getByRole('table', { name: 'Computers, as a list' });
	// 	await expect(computers.getByRole('columnheader', { name: 'Last seen' })).toHaveAttribute('aria-sort', 'descending');
	// 	await expect(computers.getByRole('row').nth(1)).toContainText('DESKTOP-1H4Q4HV');
	// 	for (const variant of VARIANTS) {
	// 		await setVariant(page, variant);
	// 		for (const width of [1440, 390]) {
	// 			await page.setViewportSize({ width, height: 900 });
	// 			await settle(page);
	// 			const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
	// 			expect.soft(scrollWidth, `horizontal scroll, ${variant} @ ${width}`).toBeLessThanOrEqual(width);
	// 			await page.screenshot({ path: testInfo.outputPath(`list-${variant}-${width}.png`), fullPage: true });
	// 		}
	// 	}
	// });
	// OLD CODE END

	test('mirror mode opens the All devices table, with no tabs, and it fits the page down to 390 px', async ({ page }, testInfo) => {
		await open(page);
		await expect(page.locator('main .type-group')).toHaveCount(0);
		for (const variant of VARIANTS) {
			await setVariant(page, variant);
			for (const width of [1440, 390]) {
				await page.setViewportSize({ width, height: 900 });
				await settle(page);
				const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
				expect.soft(scrollWidth, `horizontal scroll, ${variant} @ ${width}`).toBeLessThanOrEqual(width);
				await page.screenshot({ path: testInfo.outputPath(`all-devices-${variant}-${width}.png`), fullPage: true });
			}
		}
	});
});

/** NET-318: resizable columns, and Copy to the right of the MAC. */
test.describe('Devices table columns (NET-318)', () => {
	// every fixture MAC is locally administered (02:…); this one is a maker's address, so it has no Private tag
	const MAKER_MAC = '00:1b:63:10:00:99';
	const LIST = { ...BY_TYPE_LAYOUT.list, devices: BY_TYPE_LAYOUT.list.devices.map((d, i) => (i === 0 ? { ...d, mac: MAKER_MAC } : d)) };
	const TABLE = 'main table[aria-label="All devices"]';

	/** Each MAC cell: its text, its Copy button and its cell, as boxes. Runs in the page. */
	function macBoxes(table: string) {
		return [...document.querySelectorAll(`${table} .mac`)].map((mac) => {
			const box = (el: Element | null) => {
				const r = el!.getBoundingClientRect();
				return { left: r.left, right: r.right, mid: r.top + r.height / 2 };
			};
			return {
				mac: mac.querySelector('.mono')!.textContent,
				text: box(mac.querySelector('.mono')),
				copy: box(mac.querySelector('button')),
				cell: box(mac.closest('td')),
			};
		});
	}

	const headerWidth = async (page: Page, label: string) =>
		(await page.getByRole('columnheader', { name: label, exact: true }).boundingBox())!.width;

	test('Copy sits to the right of each MAC, on its line, at 1440 px', async ({ page }) => {
		await open(page, LIST);
		const boxes = await page.evaluate(macBoxes, TABLE);
		expect(boxes.length).toBeGreaterThan(1);
		for (const { mac, text, copy } of boxes) {
			expect.soft(copy.left, `${mac}: Copy starts after the address`).toBeGreaterThanOrEqual(text.right);
			expect.soft(Math.abs(copy.mid - text.mid), `${mac}: Copy is on the address's line`).toBeLessThanOrEqual(2);
		}
	});

	test("a drag on a handle widens its column by the pointer's distance", async ({ page }) => {
		await open(page, LIST);
		// Name is on screen at 1440 px; later columns sit past the card's edge until the table scrolls
		const before = await headerWidth(page, 'Name');
		const handle = (await page.getByRole('separator', { name: 'Resize Name column' }).boundingBox())!;
		const x = handle.x + handle.width / 2;
		const y = handle.y + handle.height / 2;
		await page.mouse.move(x, y);
		await page.mouse.down();
		await page.mouse.move(x + 30, y);
		await page.mouse.move(x + 60, y);
		await page.mouse.up();
		expect(Math.abs((await headerWidth(page, 'Name')) - before - 60)).toBeLessThanOrEqual(2);
	});

	test('at the narrowest MAC column Copy stays whole and works, private or not; widths survive a reload and Reset clears them', async ({ page }) => {
		await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
		await open(page, LIST);
		await page.getByRole('separator', { name: 'Resize MAC address column' }).focus();
		await page.keyboard.press('Home');
		expect(Math.round(await headerWidth(page, 'MAC address'))).toBe(72);
		const boxes = await page.evaluate(macBoxes, TABLE);
		const maker = boxes.find((b) => b.mac === MAKER_MAC);
		const privateMac = boxes.find((b) => b.mac?.startsWith('02:'));
		for (const [what, b] of [['maker MAC', maker], ['private MAC', privateMac]] as const) {
			expect(b, what).toBeDefined();
			expect.soft(b!.copy.left, `${what}: Copy inside its cell`).toBeGreaterThanOrEqual(b!.cell.left);
			expect.soft(b!.copy.right, `${what}: Copy inside its cell`).toBeLessThanOrEqual(b!.cell.right);
		}
		const row = page.locator(`${TABLE} tr`).filter({ hasText: MAKER_MAC });
		await row.getByRole('button', { name: 'Copy MAC address' }).click();
		await expect(row.getByRole('button', { name: 'Copied' })).toBeVisible();
		await expect(page).toHaveURL(/\/devices$/);

		await page.reload();
		await expect(page.getByRole('table', { name: 'All devices' })).toBeVisible();
		expect(Math.round(await headerWidth(page, 'MAC address'))).toBe(72);
		await page.getByRole('button', { name: 'Reset column widths' }).click();
		await expect(page.locator(TABLE)).not.toHaveClass(/is-resized/);
		expect(await headerWidth(page, 'MAC address')).toBeGreaterThan(72);
		await expect(page.getByRole('separator', { name: 'Resize IP address column' })).toBeFocused();
	});

	test('saved wide columns scroll inside the card, never the page, at 390 px', async ({ page }) => {
		await open(page, LIST);
		await page.getByRole('separator', { name: 'Resize Name column' }).focus();
		await page.keyboard.press('End');
		await page.setViewportSize({ width: 390, height: 900 });
		await settle(page);
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
	});
});
