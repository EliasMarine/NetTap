/**
 * PR 1 route coverage (PLAN.md §5.2): every page on `app` in `empty` and `error` mode,
 * plus /login signed out. The `reduced-motion` project re-runs the empty pass at 1920 in Ember.
 */
import { expect, test } from '@playwright/test';
import { APP_ROUTES } from './routes.ts';
import {
	expectNoConsoleErrors, expectReached, heldCount, releaseHeld, setMode, stubGrafana, sweep, VIEWPORTS, watchApi, watchConsole,
} from './harness.ts';

for (const mode of ['empty', 'error'] as const) {
	test.describe(`${mode} mode`, () => {
		for (const route of APP_ROUTES) {
			test(route.path, async ({ page }, testInfo) => {
				const reduced = testInfo.project.name === 'reduced-motion';
				test.skip(reduced && mode !== 'empty', 'the reduced-motion pass covers empty mode only');
				await setMode(mode);
				const errors = watchConsole(page, { allowServerErrors: mode === 'error' });
				const apiIdle = watchApi(page);
				await stubGrafana(page, mode);

				await page.setViewportSize(VIEWPORTS[0]);
				await page.goto(route.path);
				if (mode === 'error' && route.errorText) {
					await expectReached(page, route.path, route.errorText, { text: true });
				} else {
					await expectReached(page, route.path, route.marker);
				}
				await apiIdle();
				await sweep(page, testInfo, { route: route.path, mode }, reduced ? { variants: ['ember'], viewports: [VIEWPORTS[0]] } : {});
				expectNoConsoleErrors(errors, { route: route.path, mode });
			});
		}
	});
}

test.describe('signed out', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	test('/login', async ({ page }, testInfo) => {
		test.skip(testInfo.project.name === 'reduced-motion', 'covered by the app project');
		await setMode('empty');
		const errors = watchConsole(page);
		await page.goto('/login');
		await expectReached(page, '/login', 'NetTap', { scope: 'body' });
		await sweep(page, testInfo, { route: '/login', mode: 'empty' }, { shell: false });
		expectNoConsoleErrors(errors, { route: '/login', mode: 'empty' });
	});
});

// Slow mode's contract (PLAN.md §7): the fixture daemon holds every response until the test
// releases it, so a loading state can be checked for as long as it lasts. Per-route loading
// assertions arrive with the page fixtures in step C; this proves the mechanism.
test('slow mode holds responses until the test releases them', async ({ page }, testInfo) => {
	test.skip(testInfo.project.name === 'reduced-motion', 'covered by the app project');
	await setMode('slow');
	const apiIdle = watchApi(page);
	await page.setViewportSize(VIEWPORTS[0]);
	// DNS Analytics loads everything in the browser, so the HTML arrives while its data is held.
	await page.goto('/dns');
	await expectReached(page, '/dns', 'DNS Analytics');

	await expect.poll(heldCount, { message: 'responses held by the fixture daemon' }).toBeGreaterThan(0);
	await page.waitForTimeout(500);
	expect(await heldCount(), 'still held: nothing is sent until release').toBeGreaterThan(0);

	expect(await releaseHeld()).toBeGreaterThan(0);
	// Leaving slow mode sends anything the page asked for after the release.
	await setMode('populated');
	await apiIdle();
	expect(await heldCount()).toBe(0);
});
