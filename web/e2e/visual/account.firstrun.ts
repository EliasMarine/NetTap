/**
 * NET-358: change the password in Settings › Account, in two real browsers. Runs on the `firstrun`
 * instance, so the `app` instance's saved session is untouched, and only after the `firstrun` project
 * (its tests need the store without an admin; this one creates a disposable admin there).
 */
import { test, expect, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { readFileSync } from 'fs';
import path from 'path';
import { FIRSTRUN_DATA_DIR, FIRSTRUN_URL } from '../../playwright.visual.config.ts';
import { setMode } from './harness.ts';

// Synthetic credentials for a throwaway temp data dir; both satisfy the setup wizard's rules.
const USERNAME = 'account-admin';
const OLD_PASSWORD = 'Account-Old-2026';
const NEW_PASSWORD = 'Account-New-2026';

/** The real createAdmin action, as the wizard's enhanced form sends it (auth.setup.ts does the same on `app`). */
async function createAdmin(browser: Browser): Promise<void> {
	const context = await browser.newContext({ baseURL: FIRSTRUN_URL });
	await context.request.get('/setup'); // makes sure the setup code exists
	const setupCode = readFileSync(path.join(FIRSTRUN_DATA_DIR, 'setup-code'), 'utf-8').trim();
	const res = await context.request.post('/setup?/createAdmin', {
		form: { setupCode, username: USERNAME, password: OLD_PASSWORD, confirmPassword: OLD_PASSWORD },
		headers: { Origin: FIRSTRUN_URL, Accept: 'application/json', 'x-sveltekit-action': 'true' },
		maxRedirects: 0,
	});
	expect(res.status(), await res.text()).toBe(200);
	expect((await res.json()).type).toBe('success');
	await context.close();
}

async function submitLogin(page: Page, password: string): Promise<void> {
	await page.getByLabel('Username').fill(USERNAME);
	await page.getByLabel('Password').fill(password);
	await page.getByRole('button', { name: 'Sign In' }).click();
}

/** A fresh browser signed in through /login. */
async function signIn(browser: Browser): Promise<{ context: BrowserContext; page: Page }> {
	const context = await browser.newContext({ baseURL: FIRSTRUN_URL });
	const page = await context.newPage();
	await page.goto('/login');
	await submitLogin(page, OLD_PASSWORD);
	await page.waitForURL((url) => url.pathname === '/');
	return { context, page };
}

const me = (context: BrowserContext) => context.request.get('/api/auth/me').then((res) => res.status());

// Uses all 5 per-address login checks allowed a minute (login.ts): another sign-in here needs a new context or a wait.
test('a password change keeps this browser signed in, signs the other out, and only the new password works', async ({ browser }) => {
	await setMode('empty');
	await createAdmin(browser);
	const a = await signIn(browser);
	const b = await signIn(browser);
	expect(await me(a.context)).toBe(200);
	expect(await me(b.context)).toBe(200);

	// Browser A changes the password through Settings › Account
	await a.page.goto('/settings?tab=account');
	await expect(a.page.getByText(`Signed in as ${USERNAME}`)).toBeVisible();
	await a.page.getByLabel('Current password', { exact: true }).fill(OLD_PASSWORD);
	await a.page.getByLabel('New password', { exact: true }).fill(NEW_PASSWORD);
	await a.page.getByLabel('Confirm new password', { exact: true }).fill(NEW_PASSWORD);
	await a.page.getByRole('button', { name: 'Change password' }).click();
	const done = a.page.getByText(/^Password changed\. Any other browser signed in to NetTap has to sign in again\./);
	await expect(done).toBeVisible();

	// A keeps its session (the new cookie) and its page; B's old cookie is refused
	expect(await me(a.context)).toBe(200);
	expect(await me(b.context)).toBe(401);
	await expect(a.page).toHaveURL(/\/settings\?tab=account$/);
	await expect(done).toBeVisible();
	await b.page.goto('/');
	expect(new URL(b.page.url()).pathname).toBe('/login');

	// The old password no longer signs in; the new one does
	await submitLogin(b.page, OLD_PASSWORD);
	await expect(b.page.getByRole('alert')).toBeVisible();
	expect(new URL(b.page.url()).pathname).toBe('/login');
	await submitLogin(b.page, NEW_PASSWORD);
	await b.page.waitForURL((url) => url.pathname === '/');
	expect(await me(b.context)).toBe(200);

	await a.context.close();
	await b.context.close();
});
