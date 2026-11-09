/** First-run pages on the `firstrun` instance, whose data dirs the harness never writes (PLAN.md §5.2). */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import path from 'path';
import { FIRSTRUN_DATA_DIR, FIRSTRUN_URL } from '../../playwright.visual.config.ts';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

/** NET-229 follow-up: before the first admin, Go Live needs the setup code typed on Welcome. */
async function typeSetupCode(page: Page): Promise<void> {
	await page.request.get('/setup'); // makes sure the code exists
	const setupCode = readFileSync(path.join(FIRSTRUN_DATA_DIR, 'setup-code'), 'utf-8').trim();
	const res = await page.request.post('/setup?/verifyCode', {
		form: { setupCode },
		headers: { Origin: FIRSTRUN_URL, Accept: 'application/json', 'x-sveltekit-action': 'true' },
		maxRedirects: 0,
	});
	expect((await res.json()).type).toBe('success');
}

// Setup renders without the shell (no <main>), so markers are looked up in <body>; Go Live keeps the shell.
const FIRST_RUN = [
	{ path: '/setup', marker: 'Set up NetTap', shell: false },
	{ path: '/go-live', marker: 'Go Live', shell: true },
] as const;

for (const mode of ['empty', 'error'] as const) {
	for (const route of FIRST_RUN) {
		test(`${route.path} (${mode})`, async ({ page }, testInfo) => {
			await setMode(mode);
			const errors = watchConsole(page, { allowServerErrors: mode === 'error' });
			const apiIdle = watchApi(page);
			await page.setViewportSize(VIEWPORTS[0]);
			if (route.path === '/go-live') await typeSetupCode(page);
			await page.goto(route.path);
			await expectReached(page, route.path, route.marker, { scope: 'body' });
			await apiIdle();
			await sweep(page, testInfo, { route: route.path, mode }, { shell: route.shell });
			expectNoConsoleErrors(errors, { route: route.path, mode });
		});
	}
}
