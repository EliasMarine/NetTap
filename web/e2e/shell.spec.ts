/**
 * The app shell against the real server (PLAN.md §7 "new flows"): first run, signing out from
 * the sidebar, and navigation (sidebar groups and the phone menu). One serial file, because the
 * user store is shared: it starts empty and the real createAdmin action ends first run.
 */
import { test, expect, type Page } from '@playwright/test';
import fs from 'fs';
import { E2E_DATA_DIR } from '../playwright.config';

// Synthetic credentials for the throwaway E2E data dir; they satisfy setup/+page.server.ts validation.
const USERNAME = 'shell-admin';
const PASSWORD = 'Shell-Spec-2026';
const ORIGIN = 'http://localhost:3000';

async function signIn(page: Page): Promise<void> {
	await page.goto('/login');
	await page.getByLabel('Username').fill(USERNAME);
	await page.getByLabel('Password').fill(PASSWORD);
	await page.getByRole('button', { name: 'Sign In' }).click();
	await page.waitForURL((url) => url.pathname === '/');
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
	fs.rmSync(E2E_DATA_DIR, { recursive: true, force: true });
});

test.describe('first run', () => {
	test('/ goes to /setup, and /setup is reachable', async ({ page }) => {
		await page.goto('/');
		expect(new URL(page.url()).pathname).toBe('/setup');
		await expect(page.getByRole('heading', { name: 'Welcome to NetTap' })).toBeVisible();
	});

	test('/login stays reachable for an anonymous visitor', async ({ page }) => {
		const res = await page.goto('/login');
		expect(res?.status()).toBe(200);
		expect(new URL(page.url()).pathname).toBe('/login');
		await expect(page.getByLabel('Username')).toBeVisible();
	});

	test('the real createAdmin action ends first run', async ({ request }) => {
		const res = await request.post('/setup?/createAdmin', {
			form: { username: USERNAME, password: PASSWORD, confirmPassword: PASSWORD },
			headers: { Origin: ORIGIN, Accept: 'application/json', 'x-sveltekit-action': 'true' },
			maxRedirects: 0,
		});
		expect(res.status(), await res.text()).toBe(200);
		expect((await res.json()).type).toBe('success');
	});
});

test.describe('signing out', () => {
	test('the sidebar button ends the session', async ({ page, context }) => {
		await signIn(page);
		expect((await context.cookies()).some((c) => c.name === 'nettap_token')).toBe(true);

		await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Sign out' }).click();
		await page.waitForURL((url) => url.pathname === '/login');
		expect((await context.cookies()).some((c) => c.name === 'nettap_token')).toBe(false);

		await page.goto('/alerts');
		expect(new URL(page.url()).pathname).toBe('/login');
	});
});

test.describe('navigation', () => {
	test('the sidebar reaches a page in each group and marks it current', async ({ page }) => {
		await signIn(page);
		const nav = page.getByRole('navigation', { name: 'Main' });
		for (const [name, path] of [
			['Live Monitor', '/live'],
			['Alerts', '/alerts'],
			['Devices', '/devices'],
			['Settings', '/settings'],
		] as const) {
			const link = nav.getByRole('link', { name: new RegExp(`^${name}`) });
			await link.click();
			await page.waitForURL((url) => url.pathname === path);
			await expect(link).toHaveAttribute('aria-current', 'page');
		}
	});

	test('the phone menu opens, keeps focus inside and closes', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await signIn(page);
		const menu = page.getByRole('button', { name: 'Open menu' });
		const nav = page.getByRole('navigation', { name: 'Main' });
		await expect(nav).toBeHidden();

		await menu.click();
		await expect(menu).toHaveAttribute('aria-expanded', 'true');
		await expect(nav).toBeVisible();
		expect(await nav.evaluate((el) => el.contains(document.activeElement))).toBe(true);

		// Tab from the last control wraps to the first, still inside the drawer
		await nav.getByRole('button', { name: 'Sign out' }).focus();
		await page.keyboard.press('Tab');
		expect(await nav.evaluate((el) => el.contains(document.activeElement))).toBe(true);

		await page.keyboard.press('Escape');
		await expect(nav).toBeHidden();
		await expect(menu).toBeFocused();

		// choosing a link closes it too
		await menu.click();
		await nav.getByRole('link', { name: /^Alerts/ }).click();
		await page.waitForURL((url) => url.pathname === '/alerts');
		await expect(nav).toBeHidden();
	});
});
