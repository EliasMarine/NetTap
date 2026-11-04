/**
 * Live Monitor, populated (PLAN.md §5.2): GeoMap must draw its arcs on `.arc-canvas`.
 * Runs in `app` (animated) and `reduced-motion` (a static frame, redrawn only on change).
 */
import { expect, test, type Page } from '@playwright/test';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

// Six arcs of a few hundred CSS pixels each; markers are Leaflet's, not on this canvas.
const MIN_ARC_PIXELS = 1_000;
const LIVE = { route: '/live', mode: 'populated' } as const;

/** Non-transparent pixel count and a hash of every pixel on the arc canvas. */
function readArcCanvas(page: Page): Promise<{ painted: number; hash: number }> {
	return page.evaluate(() => {
		const canvas = document.querySelector<HTMLCanvasElement>('.arc-canvas');
		const ctx = canvas?.getContext('2d');
		if (!canvas || !ctx || canvas.width === 0 || canvas.height === 0) return { painted: 0, hash: 0 };
		const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
		let painted = 0;
		let hash = 0;
		for (let i = 0; i < data.length; i++) {
			hash = (hash * 31 + data[i]) | 0;
			if (i % 4 === 3 && data[i] > 0) painted++;
		}
		return { painted, hash };
	});
}

test('/live populated: arcs drawn', async ({ page }, testInfo) => {
	const reduced = testInfo.project.name === 'reduced-motion';
	await setMode('populated');
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);

	await page.setViewportSize(VIEWPORTS[0]);
	await page.goto('/live');
	await expectReached(page, '/live', /Live/);
	await apiIdle();

	await expect
		.poll(async () => (await readArcCanvas(page)).painted, { message: 'arc pixels on .arc-canvas' })
		.toBeGreaterThan(MIN_ARC_PIXELS);

	if (reduced) {
		// no animation loop: two reads ~500 ms apart are identical
		const first = await readArcCanvas(page);
		await page.waitForTimeout(500);
		const second = await readArcCanvas(page);
		expect(second, 'static frame under reduced motion').toEqual(first);
		await sweep(page, testInfo, LIVE, { variants: ['ember'], viewports: [VIEWPORTS[0]] });
	} else {
		await sweep(page, testInfo, LIVE);
	}
	expectNoConsoleErrors(errors, LIVE);
});
