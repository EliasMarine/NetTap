/**
 * Real session on the `app` instance (PLAN.md §5.2 "Getting a real session on app").
 * `app` starts in first run (empty user store); the real createAdmin action ends it.
 * No users file is hand-written, so the harness can't drift from the real auth format.
 */
import { test as setup, expect } from '@playwright/test';
import { APP_URL, STORAGE_STATE } from '../../playwright.visual.config.ts';

// Synthetic credentials for a throwaway temp data dir; they satisfy setup/+page.server.ts validation.
const USERNAME = 'visual-admin';
const PASSWORD = 'Visual-Harness-2026';

setup('create the first admin, then sign in through /login', async ({ browser }) => {
	// 1. Submit the real createAdmin action, as the wizard's enhanced form does.
	const setupContext = await browser.newContext({ baseURL: APP_URL });
	const res = await setupContext.request.post('/setup?/createAdmin', {
		form: { username: USERNAME, password: PASSWORD, confirmPassword: PASSWORD },
		headers: { Origin: APP_URL, Accept: 'application/json', 'x-sveltekit-action': 'true' },
		maxRedirects: 0,
	});
	expect(res.status(), await res.text()).toBe(200);
	expect((await res.json()).type).toBe('success');
	// 2. That context was signed in by the action; throw it away.
	await setupContext.close();

	// 3. A fresh context with no cookies: setup is complete, so /setup goes to /login.
	const context = await browser.newContext({ baseURL: APP_URL });
	const page = await context.newPage();
	await page.goto('/setup');
	expect(new URL(page.url()).pathname).toBe('/login');

	// 4. Log in through the form and land on Home.
	await page.getByLabel('Username').fill(USERNAME);
	await page.getByLabel('Password').fill(PASSWORD);
	await page.getByRole('button', { name: 'Sign In' }).click();
	await page.waitForURL((url) => url.pathname === '/');
	await context.storageState({ path: STORAGE_STATE });
	await context.close();
});
