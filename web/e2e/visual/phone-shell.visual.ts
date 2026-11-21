/**
 * NET-349, the owner's deep UI audit at 400 px: search and the notification inbox were missing on
 * phones, and Tab walked the table hidden behind the full-screen log drawer. These run in a real
 * browser because jsdom has neither showModal's inert page nor layout.
 */
import { test, expect, type Page } from '@playwright/test';
import { setMode, settle } from './harness.ts';

/** Every edge of `box` inside the viewport `width`. */
function expectWithin(box: { x: number; width: number } | null, width: number, what: string) {
	expect(box, what).not.toBeNull();
	expect(box!.x, `${what} left edge`).toBeGreaterThanOrEqual(0);
	expect(box!.x + box!.width, `${what} right edge`).toBeLessThanOrEqual(width + 0.5);
}

/** The drawer slides in with a CSS animation, which settle() (transitions only) doesn't wait for.
 * Only the drawer's own: a page can run an endless one (a live chip's pulse) that never finishes. */
async function animationsDone(page: Page): Promise<void> {
	await page.locator('dialog.detail-drawer').evaluate((d) =>
		Promise.all(d.getAnimations({ subtree: true }).map((a) => a.finished.catch(() => undefined))),
	);
}

async function focusInDialog(page: Page): Promise<boolean> {
	return page.evaluate(() => !!document.activeElement?.closest('dialog[open]'));
}

test.describe('phone top bar (NET-349)', () => {
	test.use({ hasTouch: true });
	test.beforeEach(() => setMode('populated'));

	for (const width of [390, 400]) {
		test(`search and the inbox fit at ${width} px, with both warning chips`, async ({ page }) => {
			await page.setViewportSize({ width, height: 844 });
			// The shell's daemon check answering "not ok" shows the real offline chip
			await page.route('**/api/system/ping', (route) => route.fulfill({ json: { status: 'down' } }));
			await page.goto('/');
			await settle(page);

			const search = page.locator('#global-search');
			await expect(search).toBeVisible();
			await expect(page.getByText("Can't reach NetTap")).toBeVisible();
			// The partial-refresh chip needs a failed refresh; it is the same markup, so add one beside it
			await page.locator('.topbar .top-right').evaluate((el) => {
				const chip = document.createElement('span');
				chip.className = 'chip is-warn';
				chip.textContent = 'Some data failed to refresh';
				el.prepend(chip);
			});

			const bell = page.getByRole('button', { name: /^Notifications/ });
			await expect(bell).toBeVisible();
			expectWithin(await page.locator('.topbar').boundingBox(), width, 'top bar');
			expectWithin(await bell.boundingBox(), width, 'bell');
			expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

			await bell.tap();
			const panel = page.locator('.notification-dropdown');
			await expect(panel).toBeVisible();
			expectWithin(await panel.boundingBox(), width, 'notification panel');
			// the panel opens under the bell, so the bell stays tappable and closes it
			await bell.tap();
			await expect(panel).toBeHidden();

			await search.tap();
			await search.fill('192.168.1.80');
			await search.press('Enter');
			await expect(page).not.toHaveURL(/\/$/);
		});
	}
});

test.describe('log drawer as a modal (NET-349)', () => {
	test.beforeEach(() => setMode('populated'));

	test('at 400 px it fills the screen, keeps focus inside and gives it back to the row', async ({ page }) => {
		await page.setViewportSize({ width: 400, height: 844 });
		await page.goto('/logs');
		await settle(page);
		const drawer = page.locator('dialog.detail-drawer');
		expect(await drawer.boundingBox(), 'a closed drawer takes no space').toBeNull();

		const row = page.getByRole('button', { name: /^Open log entry from/ }).first();
		await row.click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible();
		await animationsDone(page);
		const box = await dialog.boundingBox();
		expect(box).not.toBeNull();
		expect(Math.round(box!.x)).toBe(0);
		expect(Math.round(box!.y)).toBe(0);
		expect(Math.round(box!.width)).toBe(400);
		expect(Math.round(box!.height)).toBe(844);
		await expect(page.getByRole('button', { name: 'Close panel' })).toBeFocused();

		for (let i = 0; i < 30; i++) {
			await page.keyboard.press('Tab');
			expect(await focusInDialog(page), `Tab ${i + 1} left the drawer`).toBe(true);
		}
		for (let i = 0; i < 30; i++) {
			await page.keyboard.press('Shift+Tab');
			expect(await focusInDialog(page), `Shift+Tab ${i + 1} left the drawer`).toBe(true);
		}

		await page.keyboard.press('Escape');
		await expect(dialog).toBeHidden();
		await expect(row).toBeFocused();
	});

	test('on a desktop, a backdrop click closes it; a click on its edge or a drag across the edge does not', async ({ page }) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/logs');
		await settle(page);
		await page.getByRole('button', { name: /^Open log entry from/ }).first().click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toBeVisible();
		await animationsDone(page);
		const panel = (await page.locator('dialog.detail-drawer .panel').boundingBox())!;
		const y = panel.y + panel.height / 2;

		await page.mouse.click(panel.x + 2, y);
		await expect(dialog, 'a click on the inner edge').toBeVisible();

		await page.mouse.move(panel.x + 60, y);
		await page.mouse.down();
		await page.mouse.move(panel.x - 200, y, { steps: 5 });
		await page.mouse.up();
		await expect(dialog, 'a drag from inside to the backdrop').toBeVisible();

		await page.mouse.move(panel.x - 200, y);
		await page.mouse.down();
		await page.mouse.move(panel.x + 60, y, { steps: 5 });
		await page.mouse.up();
		await expect(dialog, 'a drag from the backdrop to inside').toBeVisible();

		await page.mouse.click(panel.x - 200, y);
		await expect(dialog, 'a click on the backdrop').toBeHidden();
	});
});
