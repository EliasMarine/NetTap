/** First-run pages on the `firstrun` instance, whose data dirs the harness never writes (PLAN.md §5.2). */
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import path from 'path';
import { FIRSTRUN_DATA_DIR, FIRSTRUN_URL } from '../../playwright.visual.config.ts';
import { expectNoConsoleErrors, expectReached, setMode, sweep, VIEWPORTS, watchApi, watchConsole } from './harness.ts';

/** NET-229 follow-up: before the first admin, the wizard needs the setup code typed on Welcome. */
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

// OLD CODE START — NET-277: /go-live goes to /setup until the first admin exists (its own test below)
// // Setup renders without the shell (no <main>), so markers are looked up in <body>; Go Live keeps the shell.
// const FIRST_RUN = [
// 	{ path: '/setup', marker: 'Set up NetTap', shell: false },
// 	{ path: '/go-live', marker: 'Go Live', shell: true },
// ] as const;
// OLD CODE END
// Setup renders without the shell (no <main>), so markers are looked up in <body>.
const FIRST_RUN = [{ path: '/setup', marker: 'Set up NetTap', shell: false }] as const;

for (const mode of ['empty', 'error'] as const) {
	for (const route of FIRST_RUN) {
		test(`${route.path} (${mode})`, async ({ page }, testInfo) => {
			await setMode(mode);
			const errors = watchConsole(page, { allowServerErrors: mode === 'error' });
			const apiIdle = watchApi(page);
			await page.setViewportSize(VIEWPORTS[0]);
			// OLD CODE START — NET-229: /setup now calls no API until the code is typed (its own test below)
			// if (route.path === '/go-live') await typeSetupCode(page);
			// OLD CODE END
			await typeSetupCode(page);
			await page.goto(route.path);
			await expectReached(page, route.path, route.marker, { scope: 'body' });
			await apiIdle();
			await sweep(page, testInfo, { route: route.path, mode }, { shell: route.shell });
			expectNoConsoleErrors(errors, { route: route.path, mode });
		});
	}
}

// NET-277: Go Live needs the admin the wizard creates. The hook redirects before any daemon call, so one mode is enough.
test('/go-live goes to /setup before the first admin, even with the code typed', async ({ page }) => {
	await setMode('empty');
	const errors = watchConsole(page);
	const apiIdle = watchApi(page);
	await page.setViewportSize(VIEWPORTS[0]);
	await typeSetupCode(page);
	await page.goto('/go-live');
	await expectReached(page, '/setup', 'Set up NetTap', { scope: 'body' });
	await apiIdle();
	expectNoConsoleErrors(errors, { route: '/setup', mode: 'empty' });
});

// NET-280: the setup cookie opens the wizard's API, never the bridge. This runs before the first admin
// exists, so it fails if /api/bridge is on the hook's first-run list (the `app` instance has an admin already).
test('a bridge call before the first admin gets 401 even with the setup code typed', async ({ page }) => {
	await typeSetupCode(page);
	for (const call of ['create', 'teardown', 'bypass/enable', 'bypass/disable']) {
		const res = await page.request.post(`/api/bridge/${call}`, { headers: { Origin: FIRSTRUN_URL } });
		expect(res.status(), call).toBe(401);
		expect(await res.json(), call).toEqual({ error: 'Sign in first' });
	}
});

// NET-290: before the first admin the setup cookie opens the wizard's four /api/setup calls and nothing else
// there. configure runs after the Account step, with the new admin's session.
test('configure and unlisted /api/setup paths get 401 before the first admin, even with the setup code typed', async ({ page }) => {
	await typeSetupCode(page);
	for (const [method, url] of [
		['POST', '/api/setup/configure'],
		['GET', '/api/setup/other'],
		['POST', '/api/setup/bridge/preview'],
	]) {
		const res = await page.request.fetch(url, { method, headers: { Origin: FIRSTRUN_URL } });
		expect(res.status(), `${method} ${url}`).toBe(401);
		expect(await res.json(), `${method} ${url}`).toEqual({ error: 'Sign in first' });
	}
});

// Real hook, real routes, fixture daemon: a 200 with its field, so a missing route (404), a wrong method (405)
// or a refusal can't pass. Without the code each call is turned away first.
const WIZARD_CALLS = [
	{ method: 'GET', url: '/api/setup/nics', body: undefined, field: 'source', value: 'daemon' },
	{ method: 'GET', url: '/api/setup/storage', body: undefined, field: 'source', value: 'daemon' },
	{
		method: 'POST',
		url: '/api/setup/storage',
		body: { hot_days: 90, warm_days: 180, cold_days: 30, disk_threshold_percent: 80, emergency_threshold_percent: 90 },
		field: 'saved',
		value: true,
	},
	{
		method: 'POST',
		url: '/api/setup/bridge',
		body: { wan_interface: 'enp1s0', lan_interface: 'enp2s0' },
		field: 'ready',
		value: true,
	},
] as const;

test('the wizard\'s four /api/setup calls work with the setup code typed and not without it (NET-290)', async ({ page }) => {
	await setMode('empty');
	const send = (call: (typeof WIZARD_CALLS)[number]) =>
		page.request.fetch(call.url, { method: call.method, data: call.body, headers: { Origin: FIRSTRUN_URL } });

	for (const call of WIZARD_CALLS) {
		const refused = await send(call);
		expect(refused.status(), `${call.method} ${call.url} without the code`).toBe(401);
		expect(await refused.json()).toEqual({ error: 'Enter the setup code first.' });
	}

	await typeSetupCode(page);
	for (const call of WIZARD_CALLS) {
		const res = await send(call);
		expect(res.status(), `${call.method} ${call.url}`).toBe(200);
		expect((await res.json())[call.field], `${call.method} ${call.url}`).toBe(call.value);
	}

	// SvelteKit sends a trailing slash to the canonical address (308) before the hook runs, so it is judged there
	const redirect = await page.request.get('/api/setup/storage/', { maxRedirects: 0 });
	expect(redirect.status()).toBe(308);
	// OLD CODE: expect(new URL(redirect.headers()['location'], FIRSTRUN_URL).pathname).toBe('/api/setup/storage'); (kit 3 sends a relative Location, `../storage`; NET-315)
	// A relative Location is resolved against the URL that was asked for, as a browser does
	expect(new URL(redirect.headers()['location'], `${FIRSTRUN_URL}/api/setup/storage/`).pathname).toBe('/api/setup/storage');
	expect((await page.request.get('/api/setup/storage/')).status()).toBe(200);
});

// NET-290 review: only /setup itself is a first-run page. SvelteKit strips /__data.json before the hook runs,
// so the page's own data request still arrives as `/setup`; a route that someone adds under /setup later does not
// answer before the first admin exists. (The wizard's form actions, /setup?/verifyCode, are walked by typeSetupCode.)
test('only /setup is open before the first admin: its data request is, /setup/anything is not', async ({ page }) => {
	const data = await page.request.get('/setup/__data.json');
	expect(data.status()).toBe(200);
	expect((await data.json()).type).toBe('data');

	const other = await page.request.get('/setup/anything', { maxRedirects: 0 });
	expect(other.status()).toBe(302);
	expect(new URL(other.headers()['location'], FIRSTRUN_URL).pathname).toBe('/setup');
});

// Before the code, Welcome asks only for it and calls no API (NET-229), so there is nothing to wait for
test('/setup asks for the setup code first', async ({ page }, testInfo) => {
	await setMode('empty');
	const errors = watchConsole(page);
	await page.setViewportSize(VIEWPORTS[0]);
	await page.goto('/setup');
	await expectReached(page, '/setup', 'Set up NetTap', { scope: 'body' });
	await expect(page.getByLabel('Setup code')).toBeVisible();
	await sweep(page, testInfo, { route: '/setup', mode: 'empty' }, { shell: false });
	expectNoConsoleErrors(errors, { route: '/setup', mode: 'empty' });
});
