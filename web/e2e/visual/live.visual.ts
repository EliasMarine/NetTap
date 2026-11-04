/**
 * Live Monitor, populated (PLAN.md §5.4): the DotMap draws a hotspot per destination country.
 * Runs in `app` (animated) and `reduced-motion`, where the feed starts paused and the map is a
 * static frame (PLAN.md §4.5).
 */
import { expect, test, type Page } from '@playwright/test';
import { LIVE_ROUTES } from './fixtures/live.ts';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const LIVE = { route: '/live', mode: 'populated' } as const;

// One hotspot per destination country in the populated fixture
const populated = LIVE_ROUTES[0].populated as { geo_arcs: { country_code: string }[] };
const COUNTRIES = new Set(populated.geo_arcs.map((a) => a.country_code)).size;

const map = (page: Page) => page.locator('main .map-card svg');

/** The map's markup and its running animations, to compare two moments. */
function readMap(page: Page): Promise<{ markup: string; animations: number }> {
	return map(page).evaluate((svg) => ({
		markup: svg.outerHTML,
		animations: svg.getAnimations({ subtree: true }).length,
	}));
}

test('/live populated: hotspots drawn', async ({ page }, testInfo) => {
	const reduced = testInfo.project.name === 'reduced-motion';
	await setMode('populated');
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);

	await page.setViewportSize(VIEWPORTS[0]);
	await page.goto('/live');
	await expectReached(page, '/live', /Live/);
	await apiIdle();

	// each hotspot is a focusable button named by its country and connection count
	await expect(map(page).locator('g[role="button"]'), 'one hotspot per country').toHaveCount(COUNTRIES);
	await expect(map(page).locator('.hot-core')).toHaveCount(COUNTRIES);
	await expect(map(page).getByRole('button', { name: /^United States, \d+ connections$/ })).toBeVisible();
	// home is null today, so no "Your network" ring or arcs
	await expect(map(page).locator('.arc, .home-ring')).toHaveCount(0);

	if (reduced) {
		await expect(page.locator('main .live-chip'), 'the feed starts paused').toHaveText('Paused');
		// a static frame: nothing animates, and two reads ~500 ms apart are identical
		const first = await readMap(page);
		await page.waitForTimeout(500);
		const second = await readMap(page);
		expect(first.animations, 'map animations under reduced motion').toBe(0);
		expect(second, 'static map under reduced motion').toEqual(first);
		await sweep(page, testInfo, LIVE, { variants: ['ember'], viewports: [VIEWPORTS[0]] });
	} else {
		await expect(page.locator('main .live-chip')).toHaveText('Live');
		await sweep(page, testInfo, LIVE);
	}
	expectNoConsoleErrors(errors, LIVE);
});
