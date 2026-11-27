/**
 * Live Monitor, populated. Three ways the map draws:
 * - the 3D globe (the default): it must really start, on WebGPU or WebGL 2, and move;
 * - the flat DotMap this browser picked in Settings › Display: a hotspot per destination country,
 *   the saved home's ring and arcs, and the arcs stop when the page pauses;
 * - the flat DotMap the globe fell back to when the browser has neither WebGPU nor WebGL 2.
 * Each runs in `app` (animated) and `reduced-motion` (the feed starts paused, nothing moves).
 */
import { expect, test, type Page } from '@playwright/test';
import { LIVE_ROUTES } from './fixtures/live.ts';
import { expectNoConsoleErrors, expectReached, setMode, settle, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const LIVE = { route: '/live', mode: 'populated' } as const;

// One hotspot per destination country in the populated fixture
const populated = LIVE_ROUTES[0].populated as { geo_arcs: { country_code: string }[] };
const COUNTRIES = new Set(populated.geo_arcs.map((a) => a.country_code)).size;

const card = (page: Page) => page.locator('main .globe-card');
const map = (page: Page) => card(page).locator('.globe-stage svg');
const FALLBACK_NOTE = "This browser can't draw the 3D globe, so the flat map is shown.";

/** The map's markup and its running animations, to compare two moments. */
function readMap(page: Page): Promise<{ markup: string; animations: number }> {
	return map(page).evaluate((svg) => ({
		markup: svg.outerHTML,
		animations: svg.getAnimations({ subtree: true }).length,
	}));
}

async function openLive(page: Page, init?: () => void, viewport: { width: number; height: number } = VIEWPORTS[0]) {
	await setMode('populated');
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	if (init) await page.addInitScript(init);
	// OLD CODE: await page.setViewportSize(VIEWPORTS[0]); (NET-376: the flat-map cap is checked at 2560)
	await page.setViewportSize(viewport);
	await page.goto('/live');
	await expectReached(page, '/live', /Live/);
	await apiIdle();
	return errors;
}

test('/live populated: the 3D globe starts and moves', async ({ page }, testInfo) => {
	const reduced = testInfo.project.name === 'reduced-motion';
	const errors = await openLive(page);

	// A renderer that fails to start shows the flat map and data-backend="flat": that fails here
	await expect(card(page)).toHaveAttribute('data-backend', /^(WebGPU|WebGL 2)$/, { timeout: 20_000 });
	await expect(card(page).getByText(FALLBACK_NOTE)).toHaveCount(0);
	await expect(card(page).getByText(/^Drawn with (WebGPU|WebGL 2)$/)).toBeVisible();
	await expect(card(page).locator('.globe-home')).toContainText('Your network');
	// the destinations list is the keyboard path to the country filter
	await expect(card(page).getByRole('button', { name: /^Filter by / })).toHaveCount(COUNTRIES);

	const canvas = card(page).locator('.globe-stage canvas');
	if (reduced) {
		await expect(page.locator('main .live-chip'), 'the feed starts paused').toHaveText('Paused');
		await sweep(page, testInfo, LIVE, { variants: ['ember'], viewports: [VIEWPORTS[0]] });
	} else {
		await expect(page.locator('main .live-chip')).toHaveText('Live');
		// packets and arc dashes move: two frames apart differ
		const first = await canvas.screenshot();
		await page.waitForTimeout(600);
		const second = await canvas.screenshot();
		expect(first.equals(second), 'the globe is animating').toBe(false);
		await sweep(page, testInfo, LIVE);
	}
	expectNoConsoleErrors(errors, LIVE);
});

test('/live populated: Expand fills the window as a modal, and Esc closes it even after a drag', async ({ page }) => {
	const errors = await openLive(page);
	await expect(card(page)).toHaveAttribute('data-backend', /^(WebGPU|WebGL 2)$/, { timeout: 20_000 });
	const expand = card(page).getByRole('button', { name: 'Expand' });
	await expand.click();

	const dialog = page.getByRole('dialog', { name: 'Where your traffic goes' });
	await expect(dialog).toHaveAttribute('aria-modal', 'true');
	const box = await dialog.boundingBox();
	expect(box, 'the dialog covers the window').toEqual({ x: 0, y: 0, ...page.viewportSize()! });
	await expect(page.locator('nav').first(), 'the rest of the page is inert').toHaveJSProperty('inert', true);

	// a drag on the globe takes focus off the dialog's controls
	const stage = await card(page).locator('.globe-stage canvas').boundingBox();
	await page.mouse.move(stage!.x + stage!.width / 2, stage!.y + stage!.height / 2);
	await page.mouse.down();
	await page.mouse.move(stage!.x + stage!.width / 2 + 80, stage!.y + stage!.height / 2, { steps: 4 });
	await page.mouse.up();
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect(expand).toBeFocused();
	await expect(page.locator('nav').first()).toHaveJSProperty('inert', false);
	expectNoConsoleErrors(errors, LIVE);
});

test('/live populated: the flat map this browser picked', async ({ page }, testInfo) => {
	const reduced = testInfo.project.name === 'reduced-motion';
	const errors = await openLive(page, () => localStorage.setItem('nettap-display-settings', JSON.stringify({ liveMap: 'flat' })));

	await expect(card(page)).toHaveAttribute('data-backend', 'flat');
	await expect(card(page).getByText(FALLBACK_NOTE)).toHaveCount(0);
	// each hotspot is a focusable button named by its country and connection count
	await expect(map(page).locator('g[role="button"]'), 'one hotspot per country').toHaveCount(COUNTRIES);
	await expect(map(page).locator('.hot-core')).toHaveCount(COUNTRIES);
	await expect(map(page).getByRole('button', { name: /^United States, \d+ connections$/ })).toBeVisible();
	// the saved home (London): its ring, and arcs to the busiest places
	await expect(map(page).locator('.home-ring')).toHaveCount(1);
	await expect(map(page).locator('.arc').first()).toBeAttached();

	if (reduced) {
		await expect(page.locator('main .live-chip'), 'the feed starts paused').toHaveText('Paused');
		// a static frame: nothing animates, and two reads ~500 ms apart are identical
		const first = await readMap(page);
		await page.waitForTimeout(500);
		const second = await readMap(page);
		expect(first.animations, 'map animations under reduced motion').toBe(0);
		expect(second, 'static map under reduced motion').toEqual(first);
	} else {
		const playState = () => map(page).locator('.arc').first().evaluate((el) => getComputedStyle(el).animationPlayState);
		expect(await playState()).toBe('running');
		// pausing the page stops the arcs' flow too
		await page.locator('main .page-head').getByRole('button', { name: /Auto/ }).click();
		await expect(page.locator('main .live-chip')).toHaveText('Paused');
		await expect(card(page).locator('.globe-stage')).toHaveClass(/is-paused/);
		expect(await playState()).toBe('paused');
	}
	expectNoConsoleErrors(errors, LIVE);
});

/** The flat map's stage against its grid track (the globe body's first column) and the map's own height. */
function flatGeometry(page: Page) {
	return card(page).locator('.globe-body').evaluate((body) => {
		const stage = body.querySelector('.globe-stage')!.getBoundingClientRect();
		const svg = body.querySelector('.globe-stage svg')!.getBoundingClientRect();
		const cs = getComputedStyle(body);
		const track = parseFloat(cs.gridTemplateColumns.split(' ')[0]);
		const trackLeft = body.getBoundingClientRect().left + parseFloat(cs.paddingLeft);
		return { track, stageWidth: stage.width, left: stage.left - trackLeft, right: trackLeft + track - stage.right, svgHeight: svg.height };
	});
}

const CAP = 640 / 0.44; // the globe stage's 640 px height at DotMap's 0.44 height ratio

test('/live populated: on a wide screen the flat map stops at the globe height, centred, but not when expanded (NET-376)', async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === 'reduced-motion', 'layout only: the app pass covers it');
	const errors = await openLive(page, () => localStorage.setItem('nettap-display-settings', JSON.stringify({ liveMap: 'flat' })), { width: 2560, height: 1440 });
	await expect(card(page)).toHaveAttribute('data-backend', 'flat');
	await settle(page);

	// 2560: the column is wider than the cap, so the map is capped at 640 px tall and centred in it
	const wide = await flatGeometry(page);
	expect(wide.track, '2560: the map column is wider than the cap').toBeGreaterThan(CAP + 10);
	expect(Math.abs(wide.stageWidth - CAP), '2560: the stage is capped').toBeLessThanOrEqual(1);
	expect(Math.abs(wide.svgHeight - 640), '2560: the map is the globe height').toBeLessThanOrEqual(2);
	expect(Math.abs(wide.left - wide.right), '2560: centred in its column').toBeLessThanOrEqual(2);

	// 1920: the column is narrower than the cap, so the map fills it and keeps its 0.44 shape
	await page.setViewportSize({ width: 1920, height: 1080 });
	await expect.poll(async () => Math.abs((await flatGeometry(page)).stageWidth - (await flatGeometry(page)).track), { message: '1920: the stage fills its column' }).toBeLessThanOrEqual(1);
	const mid = await flatGeometry(page);
	expect(mid.track, '1920: the column is narrower than the cap').toBeLessThan(CAP);
	await expect.poll(async () => Math.abs((await flatGeometry(page)).svgHeight - Math.round(mid.track * 0.44)), { message: '1920: the map keeps its shape' }).toBeLessThanOrEqual(2);

	// Expanded at 2560 the map uses the room; collapsed it is capped again
	await page.setViewportSize({ width: 2560, height: 1440 });
	await settle(page);
	const expand = card(page).getByRole('button', { name: 'Expand' });
	await expand.click();
	const dialog = page.getByRole('dialog', { name: 'Where your traffic goes' });
	await expect(dialog).toHaveAttribute('aria-modal', 'true');
	await expect.poll(async () => (await flatGeometry(page)).stageWidth, { message: 'expanded: not capped' }).toBeGreaterThan(CAP + 10);
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect.poll(async () => Math.abs((await flatGeometry(page)).stageWidth - CAP), { message: 'collapsed: capped again' }).toBeLessThanOrEqual(1);
	expectNoConsoleErrors(errors, LIVE);
});

test('/live populated: no WebGPU or WebGL 2, so the globe falls back to the flat map', async ({ page }) => {
	const errors = await openLive(page, () => {
		Object.defineProperty(navigator, 'gpu', { value: undefined, configurable: true });
		const getContext = HTMLCanvasElement.prototype.getContext;
		// @ts-expect-error -- narrowing the overloads is beside the point in a test stub
		HTMLCanvasElement.prototype.getContext = function (type: string, ...rest: unknown[]) {
			return type === 'webgl2' || type === 'webgpu' ? null : getContext.call(this, type, ...rest);
		};
	});

	await expect(card(page)).toHaveAttribute('data-backend', 'flat', { timeout: 20_000 });
	await expect(card(page).getByText(FALLBACK_NOTE)).toBeVisible();
	await expect(map(page).locator('.hot-core')).toHaveCount(COUNTRIES);
	await expect(map(page).locator('.home-ring')).toHaveCount(1);
	await expect(map(page).locator('.arc').first()).toBeAttached();
	expectNoConsoleErrors(errors, LIVE);
});
