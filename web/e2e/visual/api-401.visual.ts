/** NET-197: an API call with no session answers 401 JSON. A redirect to /login would be followed by
 * the browser's fetch and reach the caller as the login page's HTML with status 200, which looked
 * like success. No mocks: the real hook, a real session from auth.setup.ts and the fixture daemon. */
import { test, expect, type Page } from '@playwright/test';
import { setMode } from './harness.ts';

const API = '/api/suricata/rules/live';

/** The same call the app's own clients make: fetch() from inside the page. */
function fetchFromPage(page: Page) {
	return page.evaluate(async (url) => {
		const res = await fetch(url);
		return {
			status: res.status,
			redirected: res.redirected,
			contentType: res.headers.get('content-type'),
			body: await res.text(),
		};
	}, API);
}

test.describe('without a session (NET-197)', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	test('an API call answers 401 JSON, not the login page', async ({ page }) => {
		await page.goto('/login');
		const res = await fetchFromPage(page);
		expect(res.status, res.body.slice(0, 200)).toBe(401);
		expect(res.redirected).toBe(false);
		expect(res.contentType).toBe('application/json');
		expect(JSON.parse(res.body)).toEqual({ error: 'Sign in first' });
	});

	test('a page still goes to /login', async ({ page }) => {
		await page.goto('/alerts');
		expect(new URL(page.url()).pathname).toBe('/login');
	});

	// OLD CODE START — NET-257: a typed address sends Sec-Fetch-Site: none, refused before the sign-in redirect
	// // A form post, a new tab or a typed address sends Sec-Fetch-Dest: document, so it gets the sign-in page
	// test('an /api address opened as a page goes to /login, not raw JSON', async ({ page }) => {
	// 	await page.goto(API);
	// 	expect(new URL(page.url()).pathname).toBe('/login');
	// });
	// OLD CODE END
	// NET-257 refuses any /api request another site or the address bar starts, before the sign-in check.
	// A same-origin page load still gets the NET-197 redirect: hooks.server.test.ts, "a same-origin page
	// load of an /api address still goes to /login".
	test('a typed /api address gets 403 "Open this from NetTap itself.", not data or the sign-in page', async ({ page }) => {
		const res = await page.goto(API);
		expect(res?.status()).toBe(403);
		expect(await res?.json()).toEqual({ error: 'Open this from NetTap itself.' });
		expect(new URL(page.url()).pathname).toBe(API);
	});

	// NET-197 for a click: a link on a NetTap page opens an /api address with no session and gets the
	// sign-in page, never the route's JSON. Sec-Fetch-Dest: document and Sec-Fetch-Site: same-origin are
	// what a real click sends, so a typed address can't cover it. The first-run side of NET-280 is in
	// firstrun.visual.ts: this test runs after setup, so it passes with or without that fix.
	test('a same-origin link to an /api address goes to /login', async ({ page }) => {
		await page.goto('/login');
		await page.evaluate((href) => {
			const link = document.createElement('a');
			link.id = 'api-link';
			link.href = href;
			link.textContent = 'api';
			document.body.appendChild(link);
		}, API);
		// The page starts on /login, so watch for the redirect itself: the final URL alone proves nothing
		const [loginPage] = await Promise.all([
			page.waitForResponse((r) => new URL(r.url()).pathname === '/login' && r.request().redirectedFrom() !== null),
			page.click('#api-link'),
		]);
		const apiRequest = loginPage.request().redirectedFrom();
		expect(apiRequest).not.toBeNull();
		expect(new URL(apiRequest!.url()).pathname).toBe(API);
		expect((await apiRequest!.response())!.status()).toBe(302);
		expect(new URL(page.url()).pathname).toBe('/login');
	});
});

test('with a session the same call reaches the daemon (NET-197)', async ({ page }) => {
	await setMode('populated');
	await page.goto('/login'); // signed in, so this lands on Home
	expect(new URL(page.url()).pathname).toBe('/');
	const res = await fetchFromPage(page);
	expect(res.status, res.body.slice(0, 200)).toBe(200);
	expect(res.redirected).toBe(false);
	expect(res.contentType).toContain('application/json');
});
