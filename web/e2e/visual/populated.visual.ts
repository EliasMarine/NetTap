/** Every page on `app` with populated fixtures (PLAN.md §6 step C.3): data-filled cards, charts
 * and tables must fit every theme and width. A path without populated data answers empty. Live's
 * map has its own checks in live.visual.ts. */
import { test } from '@playwright/test';
import { APP_ROUTES } from './routes.ts';
import { expectNoConsoleErrors, expectReached, setMode, stubUpstreams, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

// OLD CODE START — only the two pages PR 1 restyled most visibly had a populated pass
// const POPULATED = [
// 	{ path: '/', marker: 'Network overview' },
// 	{ path: '/settings', marker: 'Settings' },
// ] as const;
// OLD CODE END

for (const route of APP_ROUTES) {
	test(`${route.path} populated`, async ({ page }, testInfo) => {
		test.skip(testInfo.project.name === 'reduced-motion', 'the reduced-motion pass covers empty mode only');
		await setMode('populated');
		const errors = watchConsole(page);
		const apiIdle = watchApi(page);
		await stubUpstreams(page, 'populated');
		await page.setViewportSize(VIEWPORTS[0]);
		await page.goto(route.path);
		await expectReached(page, route.path, route.marker);
		await apiIdle();
		await sweep(page, testInfo, { route: route.path, mode: 'populated' });
		expectNoConsoleErrors(errors, { route: route.path, mode: 'populated' });
	});
}
