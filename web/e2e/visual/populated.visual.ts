/** Populated fixtures for the pages PR 1 restyles most visibly (PLAN.md §5.2): Home and Settings. Live is in live.visual.ts. */
import { test } from '@playwright/test';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

const POPULATED = [
	{ path: '/', marker: 'Network overview' },
	{ path: '/settings', marker: 'Settings' },
] as const;

for (const route of POPULATED) {
	test(`${route.path} populated`, async ({ page }, testInfo) => {
		await setMode('populated');
		const errors = watchConsole(page);
		const apiIdle = watchApi(page);
		await page.setViewportSize(VIEWPORTS[0]);
		await page.goto(route.path);
		await expectReached(page, route.path, route.marker);
		await apiIdle();
		await sweep(page, testInfo, { route: route.path, mode: 'populated' });
		expectNoConsoleErrors(errors, { route: route.path, mode: 'populated' });
	});
}
