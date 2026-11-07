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
