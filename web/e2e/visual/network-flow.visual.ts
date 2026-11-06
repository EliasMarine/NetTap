/** The Network flow on /connections against the crowded fixture (NET-151): one view at every
 * width, chart labels that never overlap or leave the chart (larger text included), device
 * names where the registry has one, and an Other destinations node that isn't a button. */
import { test, expect, type Page } from '@playwright/test';
import { expectReached, setMode, stubUpstreams, watchApi } from './harness.ts';
import { UNNAMED_SOURCES } from './fixtures/traffic.ts';
import { LAN_DEVICES } from './fixtures/net-world.ts';

const FLOW_MIN_WIDTH = 640;

async function open(page: Page, width: number): Promise<void> {
	await setMode('populated');
	const apiIdle = watchApi(page);
	await stubUpstreams(page, 'populated');
	await page.setViewportSize({ width, height: 1000 });
	await page.goto('/connections');
	await expectReached(page, '/connections', 'Connections');
	await apiIdle();
	await page.locator('.flow').first().waitFor();
}

/** Every chart label's box relative to the plot, from the DOM. Runs in the page. */
function labelBoxes() {
	const plot = document.querySelector('.flow-chart .plot')!;
	const p = plot.getBoundingClientRect();
	const labels = [...plot.querySelectorAll<HTMLElement>('.lab')].map((el) => {
		const r = el.getBoundingClientRect();
		return { text: el.textContent!.trim().replace(/\s+/g, ' '), top: r.top - p.top, bottom: r.bottom - p.top, left: r.left - p.left, right: r.right - p.left };
	});
	return { width: p.width, height: p.height, labels };
}

function expectNoOverlap(found: ReturnType<typeof labelBoxes>, what: string): void {
	const { width, height, labels } = found;
	expect(labels.length, what).toBeGreaterThan(20);
	const outside = labels.filter((b) => b.top < -0.5 || b.left < -0.5 || b.bottom > height + 0.5 || b.right > width + 0.5);
	expect.soft(outside.map((b) => b.text), `${what}: labels outside the chart`).toEqual([]);
	const overlaps = labels.flatMap((a, i) =>
		labels.slice(i + 1).filter((b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5).map((b) => `${a.text} / ${b.text}`),
	);
	expect.soft(overlaps, `${what}: overlapping labels`).toEqual([]);
}

const nextFrames = (page: Page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));

test.describe('Network flow', () => {
	for (const width of [1920, 1100, 900, 390]) {
		test(`shows exactly one view at ${width} px`, async ({ page }) => {
			await open(page, width);
			const chart = await page.locator('.flow-chart').count();
			const table = await page.locator('.flow-table').count();
			expect(chart + table).toBe(1);
			const flowWidth = await page.locator('.flow').evaluate((el) => el.clientWidth);
			expect(chart === 1, `card ${flowWidth} px`).toBe(flowWidth >= FLOW_MIN_WIDTH);
			if (width === 1920) expect(chart).toBe(1);
			if (width === 390) expect(table).toBe(1);
		});
	}

	for (const width of [1920, 1100]) {
		test(`chart labels never overlap at ${width} px, with larger text too`, async ({ page }) => {
			await open(page, width);
			await expect(page.locator('.flow-chart')).toHaveCount(1);
			expectNoOverlap(await page.evaluate(labelBoxes), `${width} px`);

			await page.evaluate(() => (document.documentElement.style.fontSize = '125%'));
			await page.waitForFunction(() => Math.round(document.querySelector('.flow .probe')!.getBoundingClientRect().height) === 20);
			await nextFrames(page);
			if ((await page.locator('.flow-chart').count()) === 0) return; // the card got too narrow for the chart: the table is fine
			expectNoOverlap(await page.evaluate(labelBoxes), `${width} px at 125 % text`);
		});
	}

	test('names devices the registry knows, shows the rest by IP, and Other is not a button', async ({ page }) => {
		await open(page, 1920);
		// The name wins the room; the IP shows beside it when it fits, and is always in the button's name
		const named = LAN_DEVICES[0];
		const namedLabel = page.getByRole('button', { name: `${named.hostname} (${named.ip})` });
		await expect(namedLabel.locator('.name')).toBeVisible();
		await expect(namedLabel.locator('.name')).toHaveText(named.hostname);

		const unnamed = page.locator('.flow-chart .lab.src', { hasText: UNNAMED_SOURCES[0] });
		await expect(unnamed.locator('.name')).toHaveText(UNNAMED_SOURCES[0]);
		await expect(unnamed.locator('.ip')).toHaveCount(0);

		await expect(page.locator('.flow-chart .lab.other')).toHaveText(/Other destinations/);
		await expect(page.getByRole('button', { name: /Other destinations/ })).toHaveCount(0);
	});
});
