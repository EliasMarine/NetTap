import { test, expect, mockAllApiRoutes, MOCK_NICS } from './fixtures';
import type { Page, Route } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import os from 'os';

/** Must match E2E_DATA_DIR exported from playwright.config.ts */
const E2E_DATA_DIR = path.join(os.tmpdir(), 'nettap-e2e-data');

// Synthetic credentials for the throwaway E2E data dir; they satisfy setup/+page.server.ts validation.
const USERNAME = 'testadmin';
const PASSWORD = 'TestPass123';

const json = (body: unknown) => (route: Route) =>
	route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

/**
 * The wizard's daemon calls, answered so every step is reachable and every result is known.
 * mockAllApiRoutes answers /api/setup/nics with `source: 'mock'`, which the wizard rejects
 * (it means the daemon didn't answer, so there are no real cards to pick). The routes below are
 * registered after it, and Playwright runs the newest matching route first, so they win.
 */
async function mockWizardApis(page: Page): Promise<void> {
	await mockAllApiRoutes(page);
	await page.route('**/api/setup/nics**', json({ interfaces: MOCK_NICS, source: 'daemon' }));
	await page.route('**/api/setup/configure', json({ status: 'ok' }));
	await page.route('**/api/settings/excluded-ips', json({ excluded_ips: ['192.168.1.100'] }));
	await page.route('**/api/opensearch/cluster', json({ status: 'green' }));
}

/**
 * Mirror mode, the shortest real path: Welcome → Choose capture mode → Select capture interface
 * → Storage configuration (skipped) → Device enrichment (skipped) → Create admin account.
 * (DHCP gateway, the recommended mode, adds its subnet step; the inline bridge sits under Advanced.)
 */
async function walkToAccountStep(page: Page): Promise<void> {
	await page.goto('/setup');
	expect(new URL(page.url()).pathname).toBe('/setup');

	// Welcome: the requirements check runs on load, and Get started enables once it has finished
	await expect(page.getByRole('heading', { name: 'Welcome to NetTap' })).toBeVisible({ timeout: 10_000 });
	const start = page.getByRole('button', { name: 'Get started', exact: true });
	await expect(start).toBeEnabled({ timeout: 10_000 });
	await start.click();

	// Choose capture mode: the recommended DHCP gateway first, Mirror / SPAN second
	await expect(page.getByRole('heading', { name: 'Choose capture mode' })).toBeVisible();
	const next = page.getByRole('button', { name: 'Next', exact: true });
	await expect(next).toBeDisabled();
	await page.getByRole('button', { name: /Mirror \/ SPAN/ }).click();
	await next.click();

	// Select capture interface: Next waits for a card
	await expect(page.getByRole('heading', { name: 'Select capture interface' })).toBeVisible();
	await expect(next).toBeDisabled();
	await page.getByLabel(/Capture interface/).selectOption('eth0');
	await next.click();

	await expect(page.getByRole('heading', { name: 'Storage configuration' })).toBeVisible();
	await page.getByRole('button', { name: 'Skip', exact: true }).click();

	await expect(page.getByRole('heading', { name: 'Device enrichment' })).toBeVisible();
	await page.getByRole('button', { name: 'Skip', exact: true }).click();

	await expect(page.getByRole('heading', { name: 'Create admin account' })).toBeVisible();
}

test.describe('Setup wizard', () => {
	// Tests must run in order: test 3 creates a user, which ends first run
	test.describe.configure({ mode: 'serial' });

	// Clean up the DATA_DIR before the suite so we start with zero users
	test.beforeAll(() => {
		if (fs.existsSync(E2E_DATA_DIR)) {
			fs.rmSync(E2E_DATA_DIR, { recursive: true });
		}
	});

	test('first-run (no users) redirects to /setup', async ({ page }) => {
		// The data dir was just emptied, so hooks.server.ts sends every page to the wizard
		await page.goto('/');

		expect(new URL(page.url()).pathname).toBe('/setup');
		await expect(page.getByRole('heading', { name: 'Welcome to NetTap' })).toBeVisible({ timeout: 5_000 });
	});

	test('wizard step navigation (Welcome -> Capture mode -> Interfaces -> Storage -> Enrichment -> Account)', async ({
		page,
	}) => {
		await mockWizardApis(page);
		await walkToAccountStep(page);

		// The step indicator lists the mirror flow, with the current step marked
		const steps = page.getByRole('navigation', { name: 'Setup progress' });
		await expect(steps.locator('.step-label')).toHaveText([
			'Welcome',
			'Capture mode',
			'Interfaces',
			'Storage',
			'Enrichment',
			'Account',
			'Verification',
		]);
		await expect(steps.locator('[aria-current="step"]')).toContainText('Account');

		// The account form, with its submit disabled until the form is valid
		await expect(page.getByLabel('Setup code')).toBeVisible();
		await expect(page.getByLabel('Username')).toBeVisible();
		await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
		await expect(page.getByLabel('Confirm password')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Complete setup' })).toBeDisabled();

		// The Account step has no Back button (it never had); a done step in the indicator goes back
		await expect(page.getByRole('button', { name: 'Back', exact: true })).toHaveCount(0);
		await steps.getByRole('button', { name: /Enrichment/ }).click();
		await expect(page.getByRole('heading', { name: 'Device enrichment' })).toBeVisible();
	});

	test('account creation completes setup and shows the verification step', async ({ page }) => {
		await mockWizardApis(page);
		await walkToAccountStep(page);

		// NET-229: the one-time setup code the wizard's load made in DATA_DIR
		await page.getByLabel('Setup code').fill(fs.readFileSync(path.join(E2E_DATA_DIR, 'setup-code'), 'utf-8').trim());
		await page.getByLabel('Username').fill(USERNAME);
		await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
		await page.getByLabel('Confirm password').fill(PASSWORD);

		// No form action mock: the real server creates the account. DATA_DIR is a writable temp
		// directory (playwright.config.ts), so createFirstAdmin() writes users.json there.
		const completeBtn = page.getByRole('button', { name: 'Complete setup' });
		await expect(completeBtn).toBeEnabled();

		const [response] = await Promise.all([
			page.waitForResponse(
				(resp) => resp.request().method() === 'POST' && resp.url().includes('?/createAdmin'),
				{ timeout: 15_000 },
			),
			completeBtn.click(),
		]);
		expect(response.status()).toBe(200);

		// The wizard saves the capture settings (mocked: ok), then runs the verification checks
		await expect(page.getByRole('heading', { name: 'System verification' })).toBeVisible({ timeout: 10_000 });
		await expect(page.getByText('Cluster: green')).toBeVisible();
		await expect(page.getByText('1 IP(s) excluded')).toBeVisible();
		await expect(page.getByRole('link', { name: 'Go to dashboard' })).toBeVisible();
		await expect(page.getByRole('link', { name: 'Go Live setup' })).toBeVisible();
		await expect(page.getByRole('alert')).toHaveCount(0);
	});
});
