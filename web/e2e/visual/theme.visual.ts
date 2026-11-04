/**
 * Theme protocol (PLAN.md §6 PR 1, theme table, "Harness tests" 1–5).
 * Picker contract: radios name="theme", values ember|graphite|spectrum, accessible names
 * Ember / Graphite / Spectrum, in the Display tab of /settings (not the default tab).
 */
import { expect, test, type Page, type Route } from '@playwright/test';
import { ACCENT, expectNoConsoleErrors, setMode, watchConsole } from './harness.ts';
const NAME = { ember: 'Ember', graphite: 'Graphite', spectrum: 'Spectrum' } as const;
type Saved = 'graphite' | 'spectrum';

async function rootTheme(page: Page): Promise<{ variant: string | undefined; accent: string; bg: string }> {
	return page.evaluate(() => ({
		variant: document.documentElement.dataset.theme,
		accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim().toLowerCase(),
		bg: getComputedStyle(document.body).backgroundColor,
	}));
}

async function expectTheme(page: Page, variant: keyof typeof ACCENT): Promise<void> {
	expect(await rootTheme(page)).toEqual({
		variant: variant === 'ember' ? undefined : variant,
		accent: ACCENT[variant],
		bg: 'rgb(0, 0, 0)',
	});
}

/** Opens Settings' Display tab. The tab is server-rendered, so a click before hydration
 * does nothing: retry until the picker shows. */
async function openDisplayTab(page: Page): Promise<void> {
	await expect(async () => {
		await page.getByRole('tab', { name: 'Display' }).click();
		await expect(page.getByRole('radio', { name: 'Ember' })).toBeAttached({ timeout: 1_000 });
	}).toPass({ timeout: 15_000 });
}

test.beforeEach(async () => {
	await setMode('empty');
});

for (const saved of ['graphite', 'spectrum'] as const satisfies readonly Saved[]) {
	test(`saved ${NAME[saved]}: painted before JS, picked after hydration, kept across navigation and reload`, async ({ page }) => {
		const errors = watchConsole(page);

		// Save the variant the way setTheme does, on a page of the same origin.
		await page.goto('/tools');
		await page.evaluate((v) => localStorage.setItem('nettap-theme', v), saved);

		// 1. Hold back only JavaScript; stylesheets load normally.
		const parked: Route[] = [];
		let releaseJs!: () => void;
		const jsReleased = new Promise<void>((resolve) => (releaseJs = resolve));
		await page.route('**/_app/immutable/**/*.js', async (route) => {
			parked.push(route);
			await jsReleased;
			await route.continue();
		});
		await page.goto('/settings', { waitUntil: 'commit' });
		await page.waitForFunction(
			() =>
				document.readyState !== 'loading' &&
				document.querySelector('main') !== null &&
				[...document.querySelectorAll<HTMLLinkElement>('link[rel=stylesheet]')].every((l) => l.sheet !== null)
		);
		expect(await page.locator('link[rel=stylesheet]').count(), 'SSR stylesheets').toBeGreaterThan(0);
		expect(parked.length, 'JS requests held back').toBeGreaterThan(0);
		await expectTheme(page, saved);

		// 2. Release the JS (the route stays; later requests pass straight through): after
		// hydration the picker shows the saved variant.
		releaseJs();
		await openDisplayTab(page);
		await expect(page.getByRole('radio', { name: NAME[saved] })).toBeChecked();
		await expectTheme(page, saved);

		// 3. Survives a client-side navigation (no document reload) and a reload.
		await page.evaluate(() => ((window as unknown as { __sameDocument: boolean }).__sameDocument = true));
		await page.locator('nav a[href="/devices"]').first().click();
		await page.waitForURL((url) => url.pathname === '/devices');
		expect(await page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument)).toBe(true);
		await expectTheme(page, saved);

		await page.goto('/settings');
		await page.reload();
		await expectTheme(page, saved);
		await openDisplayTab(page);
		await expect(page.getByRole('radio', { name: NAME[saved] })).toBeChecked();

		expectNoConsoleErrors(errors, { route: '/settings', mode: 'empty' });
	});
}

test('storage denied: Ember, switching to Spectrum still works for the session', async ({ page }) => {
	const errors = watchConsole(page);
	await page.addInitScript(() => {
		Object.defineProperty(window, 'localStorage', {
			configurable: true,
			get() {
				throw new DOMException('localStorage denied by test', 'SecurityError');
			},
		});
	});

	await page.goto('/settings');
	expect(
		await page.evaluate(() => {
			try {
				void window.localStorage;
				return 'readable';
			} catch {
				return 'denied';
			}
		}),
		'the stub really denies storage'
	).toBe('denied');
	await expectTheme(page, 'ember');
	await openDisplayTab(page);
	await expect(page.getByRole('radio', { name: 'Ember' })).toBeChecked();

	// click the card a user clicks: the input is transparent under the swatch, inside its <label>
	await page.locator('label', { has: page.getByRole('radio', { name: 'Spectrum' }) }).click();
	await expectTheme(page, 'spectrum');
	await expect(page.getByRole('radio', { name: 'Spectrum' })).toBeChecked();

	// for the session only: client-side navigation keeps it
	await page.locator('nav a[href="/devices"]').first().click();
	await page.waitForURL((url) => url.pathname === '/devices');
	await expectTheme(page, 'spectrum');

	expectNoConsoleErrors(errors, { route: '/settings', mode: 'empty' });
});
