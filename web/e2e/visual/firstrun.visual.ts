/** First-run pages on the `firstrun` instance, whose data dirs the harness never writes (PLAN.md §5.2). */
import { test } from '@playwright/test';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

// Setup renders without the shell (no <main>), so markers are looked up in <body>; Go Live keeps the shell.
const FIRST_RUN = [
	{ path: '/setup', marker: 'Welcome to NetTap', shell: false },
	{ path: '/go-live', marker: 'Go Live', shell: true },
] as const;

for (const mode of ['empty', 'error'] as const) {
	for (const route of FIRST_RUN) {
		test(`${route.path} (${mode})`, async ({ page }, testInfo) => {
			await setMode(mode);
			const errors = watchConsole(page, { allowServerErrors: mode === 'error' });
			const apiIdle = watchApi(page);
			await page.setViewportSize(VIEWPORTS[0]);
			await page.goto(route.path);
			await expectReached(page, route.path, route.marker, { scope: 'body' });
			await apiIdle();
			await sweep(page, testInfo, { route: route.path, mode }, { shell: route.shell });
			expectNoConsoleErrors(errors, { route: route.path, mode });
		});
	}
}
